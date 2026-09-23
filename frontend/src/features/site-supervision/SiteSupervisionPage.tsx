// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useCallback, useMemo, useState, type ElementType } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams, Link } from 'react-router-dom';
import clsx from 'clsx';
import {
  HardHat,
  Plus,
  Search,
  CalendarDays,
  ClipboardCheck,
  FileDown,
  Trash2,
  Pencil,
  X,
  Eye,
  ShieldAlert,
  Workflow,
  BarChart3,
  ChevronRight,
} from 'lucide-react';

import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  DateDisplay,
  DismissibleInfo,
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
  fetchVisits,
  createVisit,
  updateVisit,
  deleteVisit,
  conductVisit,
  reportVisit,
  exportVisit,
  fetchVisitEntries,
  createEntry,
  refuseEntry,
  deleteEntry,
  fetchPlanVsFact,
  fetchHiddenWorks,
  fetchChangeLinks,
  fetchMeta,
  DISCIPLINES,
  VISIT_STATUSES,
  ENTRY_CATEGORIES,
  type SupervisionVisit,
  type SupervisionEntry,
  type CreateVisitPayload,
  type UpdateVisitPayload,
} from './api';
import { siteSupervisionGuide } from './siteSupervisionGuide';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
}

const prettyLabel = (s: string): string =>
  s.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

function visitStatusVariant(status: string): 'blue' | 'warning' | 'success' | 'neutral' {
  switch (status) {
    case 'planned':
      return 'blue';
    case 'conducted':
      return 'warning';
    case 'reported':
      return 'success';
    default:
      return 'neutral';
  }
}

function entryStatusVariant(status: string): 'blue' | 'warning' | 'success' | 'neutral' | 'error' {
  switch (status) {
    case 'open':
      return 'blue';
    case 'addressed':
      return 'success';
    case 'refused_motivated':
      return 'error';
    case 'closed':
      return 'neutral';
    default:
      return 'neutral';
  }
}

function categoryVariant(category: string): 'blue' | 'warning' | 'success' | 'neutral' | 'error' {
  switch (category) {
    case 'conformance':
      return 'success';
    case 'deviation':
      return 'warning';
    case 'hidden_works':
      return 'blue';
    case 'instruction':
      return 'neutral';
    case 'motivated_refusal':
      return 'error';
    default:
      return 'neutral';
  }
}

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';
const selectCls = inputCls;

/* ── Create / Edit visit modal ────────────────────────────────────────── */

interface VisitFormData {
  planned_date: string;
  actual_date: string;
  visitor: string;
  discipline: string;
  summary: string;
}

const EMPTY_VISIT_FORM: VisitFormData = {
  planned_date: '',
  actual_date: '',
  visitor: '',
  discipline: 'general',
  summary: '',
};

/**
 * The form state a visit opens with.
 *
 * Pure and module-level so the edit handler can rebuild the same baseline the
 * modal started from and send only what the user actually changed. Prefilling
 * from a row and then PATCHing every field back rewrites fields nobody opened
 * with the values they held when the list was last read, quietly undoing an
 * edit somebody else made in between.
 */
export function visitFormData(v: SupervisionVisit): VisitFormData {
  return {
    planned_date: v.planned_date || '',
    actual_date: v.actual_date || '',
    visitor: v.visitor || '',
    discipline: v.discipline || 'general',
    summary: v.summary || '',
  };
}

function VisitFormModal({
  onClose,
  onSubmit,
  isPending,
  initialData,
  isEdit,
}: {
  onClose: () => void;
  onSubmit: (data: VisitFormData) => void;
  isPending: boolean;
  initialData?: VisitFormData | null;
  isEdit?: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<VisitFormData>(initialData ?? EMPTY_VISIT_FORM);

  const set = <K extends keyof VisitFormData>(key: K, value: VisitFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  return (
    <WideModal
      open
      onClose={onClose}
      size="md"
      title={
        isEdit
          ? t('site_supervision.edit_visit', { defaultValue: 'Edit visit' })
          : t('site_supervision.new_visit', { defaultValue: 'New visit' })
      }
      busy={isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={() => onSubmit(form)} loading={isPending}>
            {isEdit
              ? t('common.save', { defaultValue: 'Save' })
              : t('site_supervision.create_visit', { defaultValue: 'Create visit' })}
          </Button>
        </>
      }
    >
      <WideModalSection>
        <WideModalField label={t('site_supervision.planned_date', { defaultValue: 'Planned date' })}>
          <input
            type="date"
            className={inputCls}
            value={form.planned_date}
            onChange={(e) => set('planned_date', e.target.value)}
          />
        </WideModalField>
        <WideModalField label={t('site_supervision.actual_date', { defaultValue: 'Actual date' })}>
          <input
            type="date"
            className={inputCls}
            value={form.actual_date}
            onChange={(e) => set('actual_date', e.target.value)}
          />
        </WideModalField>
        <WideModalField label={t('site_supervision.visitor', { defaultValue: 'Visitor' })}>
          <input
            type="text"
            className={inputCls}
            placeholder={t('site_supervision.visitor_placeholder', {
              defaultValue: 'Name of the supervising engineer / architect',
            })}
            value={form.visitor}
            onChange={(e) => set('visitor', e.target.value)}
          />
        </WideModalField>
        <WideModalField label={t('site_supervision.discipline', { defaultValue: 'Discipline' })}>
          <select
            className={selectCls}
            value={form.discipline}
            onChange={(e) => set('discipline', e.target.value)}
          >
            {DISCIPLINES.map((d) => (
              <option key={d} value={d}>
                {prettyLabel(d)}
              </option>
            ))}
          </select>
        </WideModalField>
      </WideModalSection>
      <WideModalSection>
        <WideModalField
          label={t('site_supervision.summary', { defaultValue: 'Summary' })}
          className="sm:col-span-2 lg:col-span-3"
        >
          <textarea
            className={textareaCls}
            rows={4}
            placeholder={t('site_supervision.summary_placeholder', {
              defaultValue: 'What was the overall purpose and outcome of this visit?',
            })}
            value={form.summary}
            onChange={(e) => set('summary', e.target.value)}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Create entry modal ───────────────────────────────────────────────── */

interface EntryFormData {
  ordinal: string;
  category: string;
  observation: string;
  links_to_change_ref: string;
}

const EMPTY_ENTRY_FORM: EntryFormData = {
  ordinal: '',
  category: 'conformance',
  observation: '',
  links_to_change_ref: '',
};

function EntryFormModal({
  onClose,
  onSubmit,
  isPending,
}: {
  onClose: () => void;
  onSubmit: (data: EntryFormData) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<EntryFormData>(EMPTY_ENTRY_FORM);
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof EntryFormData>(key: K, value: EntryFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const canSubmit = form.observation.trim().length > 0;

  return (
    <WideModal
      open
      onClose={onClose}
      size="md"
      title={t('site_supervision.new_entry', { defaultValue: 'Log an observation' })}
      busy={isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => {
              setTouched(true);
              if (canSubmit) onSubmit(form);
            }}
            loading={isPending}
          >
            {t('site_supervision.log_entry', { defaultValue: 'Log entry' })}
          </Button>
        </>
      }
    >
      <WideModalSection>
        <WideModalField label={t('site_supervision.ordinal', { defaultValue: 'Item no.' })}>
          <input
            type="text"
            className={inputCls}
            placeholder="01"
            value={form.ordinal}
            onChange={(e) => set('ordinal', e.target.value)}
          />
        </WideModalField>
        <WideModalField label={t('site_supervision.category', { defaultValue: 'Category' })}>
          <select
            className={selectCls}
            value={form.category}
            onChange={(e) => set('category', e.target.value)}
          >
            {ENTRY_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {prettyLabel(c)}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('site_supervision.change_ref', { defaultValue: 'Change reference' })}>
          <input
            type="text"
            className={inputCls}
            placeholder={t('site_supervision.change_ref_placeholder', {
              defaultValue: 'Optional link to a change / MOC reference',
            })}
            value={form.links_to_change_ref}
            onChange={(e) => set('links_to_change_ref', e.target.value)}
          />
        </WideModalField>
      </WideModalSection>
      <WideModalSection>
        <WideModalField
          label={t('site_supervision.observation', { defaultValue: 'Observation' })}
          error={touched && !canSubmit ? t('site_supervision.observation_required', { defaultValue: 'An observation is required.' }) : undefined}
          className="sm:col-span-2 lg:col-span-3"
        >
          <textarea
            className={textareaCls}
            rows={5}
            placeholder={t('site_supervision.observation_placeholder', {
              defaultValue: 'What was observed, instructed, or accepted?',
            })}
            value={form.observation}
            onChange={(e) => set('observation', e.target.value)}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Refuse entry modal ───────────────────────────────────────────────── */

function RefuseEntryModal({
  onClose,
  onSubmit,
  isPending,
}: {
  onClose: () => void;
  onSubmit: (reason: string) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  const [touched, setTouched] = useState(false);
  const canSubmit = reason.trim().length > 0;

  return (
    <WideModal
      open
      onClose={onClose}
      size="sm"
      title={t('site_supervision.refuse_entry', { defaultValue: 'Motivated refusal' })}
      busy={isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              setTouched(true);
              if (canSubmit) onSubmit(reason.trim());
            }}
            loading={isPending}
          >
            {t('site_supervision.confirm_refusal', { defaultValue: 'Record refusal' })}
          </Button>
        </>
      }
    >
      <WideModalSection>
        <WideModalField
          label={t('site_supervision.refusal_reason', { defaultValue: 'Reason' })}
          error={touched && !canSubmit ? t('site_supervision.refusal_reason_required', { defaultValue: 'A reason is required.' }) : undefined}
          className="sm:col-span-2"
        >
          <textarea
            className={textareaCls}
            rows={4}
            autoFocus
            placeholder={t('site_supervision.refusal_reason_placeholder', {
              defaultValue: 'Why is this item being refused?',
            })}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Insight panels ────────────────────────────────────────────────────── */

type InsightTab = 'plan_vs_fact' | 'hidden_works' | 'change_links';

function InsightPanels({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<InsightTab>('plan_vs_fact');

  const planVsFactQuery = useQuery({
    queryKey: ['site-supervision-plan-vs-fact', projectId],
    queryFn: () => fetchPlanVsFact(projectId),
    enabled: !!projectId && tab === 'plan_vs_fact',
  });
  const hiddenWorksQuery = useQuery({
    queryKey: ['site-supervision-hidden-works', projectId],
    queryFn: () => fetchHiddenWorks(projectId),
    enabled: !!projectId && tab === 'hidden_works',
  });
  const changeLinksQuery = useQuery({
    queryKey: ['site-supervision-change-links', projectId],
    queryFn: () => fetchChangeLinks(projectId),
    enabled: !!projectId && tab === 'change_links',
  });

  const tabs: { id: InsightTab; label: string; icon: ElementType }[] = [
    {
      id: 'plan_vs_fact',
      label: t('site_supervision.plan_vs_fact', { defaultValue: 'Plan vs fact' }),
      icon: BarChart3,
    },
    {
      id: 'hidden_works',
      label: t('site_supervision.hidden_works', { defaultValue: 'Hidden works' }),
      icon: Eye,
    },
    {
      id: 'change_links',
      label: t('site_supervision.change_links', { defaultValue: 'Change links' }),
      icon: Workflow,
    },
  ];

  return (
    <Card padding="md" className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {tabs.map((tb) => {
          const Icon = tb.icon;
          return (
            <button
              key={tb.id}
              type="button"
              onClick={() => setTab(tb.id)}
              className={clsx(
                'inline-flex items-center gap-1.5 rounded-lg border px-3 h-8 text-xs font-medium transition-colors',
                tab === tb.id
                  ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                  : 'border-border text-content-secondary hover:bg-surface-secondary',
              )}
            >
              <Icon size={13} />
              {tb.label}
            </button>
          );
        })}
      </div>

      {tab === 'plan_vs_fact' && (
        <div>
          {planVsFactQuery.isLoading ? (
            <SkeletonTable rows={2} columns={4} />
          ) : planVsFactQuery.isError ? (
            <p className="text-sm text-semantic-error">
              {t('site_supervision.load_failed', { defaultValue: 'Could not load this panel.' })}
            </p>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                {
                  label: t('site_supervision.planned_count', { defaultValue: 'Planned' }),
                  value: planVsFactQuery.data?.planned_count ?? 0,
                },
                {
                  label: t('site_supervision.conducted_count', { defaultValue: 'Conducted' }),
                  value: planVsFactQuery.data?.conducted_count ?? 0,
                },
                {
                  label: t('site_supervision.reported_count', { defaultValue: 'Reported' }),
                  value: planVsFactQuery.data?.reported_count ?? 0,
                },
                {
                  label: t('site_supervision.overdue_count', { defaultValue: 'Overdue' }),
                  value: planVsFactQuery.data?.overdue_count ?? 0,
                  danger: (planVsFactQuery.data?.overdue_count ?? 0) > 0,
                },
              ].map((stat) => (
                <div
                  key={stat.label}
                  className="rounded-lg border border-border-light bg-surface-secondary/40 p-3"
                >
                  <p
                    className={clsx(
                      'text-xl font-semibold',
                      stat.danger ? 'text-semantic-error' : 'text-content-primary',
                    )}
                  >
                    {stat.value}
                  </p>
                  <p className="text-xs text-content-tertiary">{stat.label}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === 'hidden_works' && (
        <div>
          {hiddenWorksQuery.isLoading ? (
            <SkeletonTable rows={3} columns={3} />
          ) : hiddenWorksQuery.isError ? (
            <p className="text-sm text-semantic-error">
              {t('site_supervision.load_failed', { defaultValue: 'Could not load this panel.' })}
            </p>
          ) : (hiddenWorksQuery.data ?? []).length === 0 ? (
            <p className="text-sm text-content-tertiary">
              {t('site_supervision.no_hidden_works', {
                defaultValue: 'No hidden-works acceptance items recorded yet.',
              })}
            </p>
          ) : (
            <ul className="space-y-2">
              {(hiddenWorksQuery.data ?? []).map((row) => (
                <li
                  key={row.entry_id}
                  className="flex items-start gap-2 rounded-lg border border-border-light p-2.5 text-sm"
                >
                  <ShieldAlert size={14} className="mt-0.5 shrink-0 text-oe-blue" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate">{row.observation || row.ordinal || row.entry_id}</p>
                    <p className="text-xs text-content-tertiary">
                      {row.visit_date ? <DateDisplay value={row.visit_date} /> : null}
                    </p>
                  </div>
                  <Badge variant={entryStatusVariant(row.status)} size="sm">
                    {prettyLabel(row.status)}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {tab === 'change_links' && (
        <div>
          {changeLinksQuery.isLoading ? (
            <SkeletonTable rows={3} columns={3} />
          ) : changeLinksQuery.isError ? (
            <p className="text-sm text-semantic-error">
              {t('site_supervision.load_failed', { defaultValue: 'Could not load this panel.' })}
            </p>
          ) : (changeLinksQuery.data ?? []).length === 0 ? (
            <p className="text-sm text-content-tertiary">
              {t('site_supervision.no_change_links', {
                defaultValue: 'No instructions or deviations feed the change route yet.',
              })}
            </p>
          ) : (
            <ul className="space-y-2">
              {(changeLinksQuery.data ?? []).map((row) => (
                <li
                  key={row.entry_id}
                  className="flex items-start gap-2 rounded-lg border border-border-light p-2.5 text-sm"
                >
                  <Workflow size={14} className="mt-0.5 shrink-0 text-oe-blue" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate">{row.observation}</p>
                    <p className="text-xs text-content-tertiary">
                      {row.links_to_change_ref ? (
                        <Link
                          to="/changeorders"
                          className="text-oe-blue hover:underline"
                          title={t('site_supervision.open_change_orders', {
                            defaultValue: 'Open Change Orders',
                          })}
                        >
                          {t('site_supervision.change_ref_label', {
                            defaultValue: 'Change ref: {{ref}}',
                            ref: row.links_to_change_ref,
                          })}
                        </Link>
                      ) : (
                        t('site_supervision.no_change_ref', { defaultValue: 'No change reference yet' })
                      )}
                    </p>
                  </div>
                  <Badge variant={categoryVariant(row.category)} size="sm">
                    {prettyLabel(row.category)}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}

/* ── Visit detail (entries log) ───────────────────────────────────────── */

function VisitDetail({
  visit,
  onClose,
}: {
  visit: SupervisionVisit;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const [showEntryModal, setShowEntryModal] = useState(false);
  const [refusingEntry, setRefusingEntry] = useState<SupervisionEntry | null>(null);

  const entriesQuery = useQuery({
    queryKey: ['site-supervision-entries', visit.id],
    queryFn: () => fetchVisitEntries(visit.id),
  });

  const invalidateEntries = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['site-supervision-entries', visit.id] });
    qc.invalidateQueries({ queryKey: ['site-supervision-hidden-works'] });
    qc.invalidateQueries({ queryKey: ['site-supervision-change-links'] });
  }, [qc, visit.id]);

  const createEntryMut = useMutation({
    mutationFn: (data: { ordinal: string; category: string; observation: string; links_to_change_ref: string }) =>
      createEntry({
        visit_id: visit.id,
        ordinal: data.ordinal,
        category: data.category,
        observation: data.observation,
        links_to_change_ref: data.links_to_change_ref || null,
      }),
    onSuccess: () => {
      invalidateEntries();
      setShowEntryModal(false);
      addToast({ type: 'success', title: t('site_supervision.entry_logged', { defaultValue: 'Entry logged' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const refuseMut = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => refuseEntry(id, reason),
    onSuccess: () => {
      invalidateEntries();
      setRefusingEntry(null);
      addToast({ type: 'success', title: t('site_supervision.entry_refused', { defaultValue: 'Refusal recorded' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const deleteEntryMut = useMutation({
    mutationFn: (id: string) => deleteEntry(id),
    onSuccess: () => {
      invalidateEntries();
      addToast({ type: 'success', title: t('site_supervision.entry_deleted', { defaultValue: 'Entry deleted' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const handleDeleteEntry = useCallback(
    async (entry: SupervisionEntry) => {
      const ok = await confirm({
        title: t('site_supervision.confirm_delete_entry_title', { defaultValue: 'Delete entry?' }),
        message: t('site_supervision.confirm_delete_entry_msg', {
          defaultValue: 'This permanently removes this log entry.',
        }),
        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
        variant: 'danger',
      });
      if (ok) deleteEntryMut.mutate(entry.id);
    },
    [confirm, deleteEntryMut, t],
  );

  const entries = entriesQuery.data ?? [];

  return (
    <Card padding="md" className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-content-primary">
              {t('site_supervision.visit_log', { defaultValue: 'Visit log' })}
            </h3>
            <Badge variant={visitStatusVariant(visit.status)} size="sm">
              {prettyLabel(visit.status)}
            </Badge>
          </div>
          <p className="mt-1 text-xs text-content-tertiary">
            {visit.visitor || t('site_supervision.no_visitor', { defaultValue: 'No visitor recorded' })}
            {' · '}
            {prettyLabel(visit.discipline)}
            {visit.actual_date ? (
              <>
                {' · '}
                <DateDisplay value={visit.actual_date} />
              </>
            ) : visit.planned_date ? (
              <>
                {' · '}
                <DateDisplay value={visit.planned_date} />
              </>
            ) : null}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={() => setShowEntryModal(true)}>
            {t('site_supervision.log_entry', { defaultValue: 'Log entry' })}
          </Button>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="rounded-lg p-1.5 text-content-tertiary hover:bg-surface-secondary"
          >
            <X size={16} />
          </button>
        </div>
      </div>

      {visit.summary && (
        <p className="rounded-lg bg-surface-secondary/50 p-3 text-sm text-content-secondary whitespace-pre-wrap">
          {visit.summary}
        </p>
      )}

      {entriesQuery.isLoading ? (
        <SkeletonTable rows={3} columns={3} />
      ) : entries.length === 0 ? (
        <EmptyState
          icon={<ClipboardCheck size={28} />}
          title={t('site_supervision.no_entries', { defaultValue: 'No entries logged yet' })}
          description={t('site_supervision.no_entries_desc', {
            defaultValue: 'Record observations, deviations, instructions and hidden-works items as you find them on site.',
          })}
          action={{
            label: t('site_supervision.log_entry', { defaultValue: 'Log entry' }),
            onClick: () => setShowEntryModal(true),
          }}
        />
      ) : (
        <ul className="space-y-2">
          {entries.map((entry) => (
            <li key={entry.id} className="rounded-lg border border-border-light p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {entry.ordinal && (
                      <span className="font-mono text-xs text-content-tertiary">{entry.ordinal}</span>
                    )}
                    <Badge variant={categoryVariant(entry.category)} size="sm">
                      {prettyLabel(entry.category)}
                    </Badge>
                    <Badge variant={entryStatusVariant(entry.status)} size="sm">
                      {prettyLabel(entry.status)}
                    </Badge>
                    {entry.links_to_change_ref && (
                      <Link
                        to="/changeorders"
                        className="inline-flex items-center gap-0.5 rounded-full bg-oe-blue/10 px-2 py-0.5 text-xs font-medium text-oe-blue hover:bg-oe-blue/20 hover:underline"
                        title={t('site_supervision.open_change_orders', {
                          defaultValue: 'Open Change Orders',
                        })}
                      >
                        <Workflow size={10} className="shrink-0" />
                        {entry.links_to_change_ref}
                      </Link>
                    )}
                  </div>
                  <p className="mt-1.5 text-sm text-content-primary whitespace-pre-wrap">{entry.observation}</p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {entry.status !== 'refused_motivated' && entry.status !== 'closed' && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setRefusingEntry(entry)}
                      title={t('site_supervision.refuse_entry', { defaultValue: 'Motivated refusal' })}
                    >
                      <ShieldAlert size={14} />
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void handleDeleteEntry(entry)}
                    title={t('common.delete', { defaultValue: 'Delete' })}
                  >
                    <Trash2 size={14} />
                  </Button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {showEntryModal && (
        <EntryFormModal
          onClose={() => setShowEntryModal(false)}
          isPending={createEntryMut.isPending}
          onSubmit={(data) => createEntryMut.mutate(data)}
        />
      )}

      {refusingEntry && (
        <RefuseEntryModal
          onClose={() => setRefusingEntry(null)}
          isPending={refuseMut.isPending}
          onSubmit={(reason) => refuseMut.mutate({ id: refusingEntry.id, reason })}
        />
      )}

      <ConfirmDialog {...confirmProps} />
    </Card>
  );
}

/* ── Main page ─────────────────────────────────────────────────────────── */

export function SiteSupervisionPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingVisit, setEditingVisit] = useState<SupervisionVisit | null>(null);
  const [selectedVisitId, setSelectedVisitId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [disciplineFilter, setDisciplineFilter] = useState<string>('');
  const { confirm, ...confirmProps } = useConfirm();

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
    staleTime: 5 * 60_000,
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const selectedProjectId = routeProjectId || activeProjectId || '';
  const projectName = projects.find((p) => p.id === selectedProjectId)?.name || '';

  const {
    data: visits = [],
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ['site-supervision-visits', projectId, statusFilter, disciplineFilter],
    queryFn: () =>
      fetchVisits({
        project_id: projectId,
        status: statusFilter || undefined,
        discipline: disciplineFilter || undefined,
      }),
    enabled: !!projectId,
  });

  useQuery({
    queryKey: ['site-supervision-meta'],
    queryFn: fetchMeta,
    staleTime: 30 * 60_000,
  });

  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return visits;
    const q = searchQuery.toLowerCase();
    return visits.filter(
      (v) => v.visitor.toLowerCase().includes(q) || v.summary.toLowerCase().includes(q),
    );
  }, [visits, searchQuery]);

  const invalidateVisits = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['site-supervision-visits'] });
    qc.invalidateQueries({ queryKey: ['site-supervision-plan-vs-fact'] });
  }, [qc]);

  const createMut = useMutation({
    mutationFn: (data: CreateVisitPayload) => createVisit(data),
    onSuccess: () => {
      invalidateVisits();
      setShowCreateModal(false);
      addToast({ type: 'success', title: t('site_supervision.visit_created', { defaultValue: 'Visit created' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateVisitPayload }) => updateVisit(id, data),
    onSuccess: () => {
      invalidateVisits();
      setEditingVisit(null);
      addToast({ type: 'success', title: t('site_supervision.visit_updated', { defaultValue: 'Visit updated' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteVisit(id),
    onSuccess: (_data, id) => {
      invalidateVisits();
      if (selectedVisitId === id) setSelectedVisitId(null);
      addToast({ type: 'success', title: t('site_supervision.visit_deleted', { defaultValue: 'Visit deleted' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const conductMut = useMutation({
    mutationFn: (id: string) => conductVisit(id),
    onSuccess: () => {
      invalidateVisits();
      addToast({ type: 'success', title: t('site_supervision.visit_conducted', { defaultValue: 'Visit marked as conducted' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const reportMut = useMutation({
    mutationFn: (id: string) => reportVisit(id),
    onSuccess: () => {
      invalidateVisits();
      addToast({ type: 'success', title: t('site_supervision.visit_reported', { defaultValue: 'Visit marked as reported' }) });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
  });

  const handleExport = useCallback(
    async (visit: SupervisionVisit) => {
      try {
        await exportVisit(visit);
      } catch (e) {
        addToast({
          type: 'error',
          title: t('site_supervision.export_failed', { defaultValue: 'Export failed' }),
          message: e instanceof Error ? e.message : undefined,
        });
      }
    },
    [addToast, t],
  );

  const handleDelete = useCallback(
    async (visit: SupervisionVisit) => {
      const ok = await confirm({
        title: t('site_supervision.confirm_delete_visit_title', { defaultValue: 'Delete visit?' }),
        message: t('site_supervision.confirm_delete_visit_msg', {
          defaultValue: 'This permanently removes the visit and every entry logged against it.',
        }),
        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
        variant: 'danger',
      });
      if (ok) deleteMut.mutate(visit.id);
    },
    [confirm, deleteMut, t],
  );

  const buildPayload = useCallback(
    (formData: VisitFormData) => ({
      planned_date: formData.planned_date || null,
      actual_date: formData.actual_date || null,
      visitor: formData.visitor,
      discipline: formData.discipline,
      summary: formData.summary,
    }),
    [],
  );

  const handleCreateSubmit = useCallback(
    (formData: VisitFormData) => {
      if (!projectId) {
        addToast({
          type: 'error',
          title: t('common.error', { defaultValue: 'Error' }),
          message: t('common.select_project_first', { defaultValue: 'Please select a project first' }),
        });
        return;
      }
      createMut.mutate({ project_id: projectId, ...buildPayload(formData) });
    },
    [createMut, projectId, addToast, t, buildPayload],
  );

  const handleEditSubmit = useCallback(
    (formData: VisitFormData) => {
      if (!editingVisit) return;
      // Rebuild the baseline the modal started from, so the save carries only
      // what the user actually edited. See `visitFormData`.
      updateMut.mutate({
        id: editingVisit.id,
        data: onlyChangedFields(buildPayload(formData), formData, visitFormData(editingVisit)),
      });
    },
    [updateMut, editingVisit, buildPayload],
  );

  const selectedVisit = visits.find((v) => v.id === selectedVisitId) || null;

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(selectedProjectId && projectName
            ? [{ label: projectName, to: `/projects/${selectedProjectId}` }]
            : []),
          { label: t('site_supervision.title', { defaultValue: 'Site Supervision' }) },
        ]}
      />

      <PageHeader
        srTitle={t('site_supervision.title', { defaultValue: 'Site Supervision' })}
        subtitle={t('site_supervision.subtitle', {
          defaultValue: 'Plan supervision visits, log observations on site, and track hidden works before they are covered',
        })}
        actions={
          <>
            <ModuleGuideButton content={siteSupervisionGuide} />
            <Button
              variant="primary"
              size="sm"
              onClick={() => setShowCreateModal(true)}
              disabled={!projectId}
              title={!projectId ? t('common.select_project_first', { defaultValue: 'Please select a project first' }) : undefined}
              className="shrink-0 whitespace-nowrap"
              icon={<Plus size={14} />}
            >
              {t('site_supervision.new_visit', { defaultValue: 'New visit' })}
            </Button>
          </>
        }
      />

      <DismissibleInfo
        storageKey="site_supervision"
        title={t('site_supervision.intro_title', {
          defaultValue: 'Every site visit, on record before it is forgotten',
        })}
      >
        {t('site_supervision.intro_body', {
          defaultValue:
            'Log each supervision visit as it happens: who went, what discipline, and what was observed. Flag hidden works for acceptance before they are covered, and feed instructions or deviations into the change route so nothing gets lost between the site and the office.',
        })}
      </DismissibleInfo>

      {!projectId ? (
        <EmptyState
          icon={<HardHat size={28} />}
          title={t('common.select_project_first', { defaultValue: 'Please select a project first' })}
        />
      ) : (
        <>
          <Card padding="sm" className="flex flex-wrap items-center gap-2">
            <div className="relative flex-1 min-w-[200px]">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary" />
              <input
                type="text"
                className={clsx(inputCls, 'pl-9')}
                placeholder={t('site_supervision.search_placeholder', { defaultValue: 'Search visitor or summary...' })}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
            <select
              className={clsx(selectCls, 'w-auto min-w-[130px]')}
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="">{t('site_supervision.all_statuses', { defaultValue: 'All statuses' })}</option>
              {VISIT_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {prettyLabel(s)}
                </option>
              ))}
            </select>
            <select
              className={clsx(selectCls, 'w-auto min-w-[150px]')}
              value={disciplineFilter}
              onChange={(e) => setDisciplineFilter(e.target.value)}
            >
              <option value="">{t('site_supervision.all_disciplines', { defaultValue: 'All disciplines' })}</option>
              {DISCIPLINES.map((d) => (
                <option key={d} value={d}>
                  {prettyLabel(d)}
                </option>
              ))}
            </select>
          </Card>

          <InsightPanels projectId={projectId} />

          {isLoading ? (
            <SkeletonTable rows={5} columns={4} />
          ) : isError ? (
            <Card padding="md" className="text-center">
              <p className="text-sm text-semantic-error">
                {t('site_supervision.load_failed_visits', { defaultValue: 'Could not load supervision visits.' })}
              </p>
              <Button variant="secondary" size="sm" className="mt-3" onClick={() => void refetch()}>
                {t('common.retry', { defaultValue: 'Retry' })}
              </Button>
            </Card>
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={<HardHat size={28} />}
              title={t('site_supervision.no_visits', { defaultValue: 'No supervision visits yet' })}
              description={t('site_supervision.no_visits_desc', {
                defaultValue: 'Plan your first site visit to start the supervision log for this project.',
              })}
              action={{
                label: t('site_supervision.new_visit', { defaultValue: 'New visit' }),
                onClick: () => setShowCreateModal(true),
              }}
            />
          ) : (
            <div className="space-y-2">
              {filtered.map((visit) => (
                <Card key={visit.id} padding="sm" hoverable className="space-y-0">
                  <div
                    className="flex flex-wrap items-center gap-3 cursor-pointer"
                    onClick={() => setSelectedVisitId(selectedVisitId === visit.id ? null : visit.id)}
                  >
                    <ChevronRight
                      size={16}
                      className={clsx(
                        'shrink-0 text-content-tertiary transition-transform',
                        selectedVisitId === visit.id && 'rotate-90',
                      )}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-content-primary">
                          {visit.visitor || t('site_supervision.no_visitor', { defaultValue: 'No visitor recorded' })}
                        </span>
                        <Badge variant={visitStatusVariant(visit.status)} size="sm">
                          {prettyLabel(visit.status)}
                        </Badge>
                        <Badge variant="neutral" size="sm">
                          {prettyLabel(visit.discipline)}
                        </Badge>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-content-tertiary">
                        <span className="inline-flex items-center gap-1">
                          <CalendarDays size={11} />
                          {visit.actual_date ? (
                            <DateDisplay value={visit.actual_date} />
                          ) : visit.planned_date ? (
                            <DateDisplay value={visit.planned_date} />
                          ) : (
                            t('site_supervision.no_date', { defaultValue: 'No date set' })
                          )}
                        </span>
                        {visit.summary && (
                          <span className="truncate max-w-[40ch]">{visit.summary}</span>
                        )}
                      </div>
                    </div>
                    <div
                      className="flex shrink-0 items-center gap-1"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {visit.status === 'planned' && (
                        <Button
                          variant="secondary"
                          size="sm"
                          loading={conductMut.isPending && conductMut.variables === visit.id}
                          onClick={() => conductMut.mutate(visit.id)}
                        >
                          {t('site_supervision.conduct', { defaultValue: 'Conduct' })}
                        </Button>
                      )}
                      {visit.status === 'conducted' && (
                        <Button
                          variant="secondary"
                          size="sm"
                          loading={reportMut.isPending && reportMut.variables === visit.id}
                          onClick={() => reportMut.mutate(visit.id)}
                        >
                          {t('site_supervision.report', { defaultValue: 'Report' })}
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => void handleExport(visit)}
                        title={t('site_supervision.export', { defaultValue: 'Export' })}
                      >
                        <FileDown size={14} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setEditingVisit(visit)}
                        title={t('common.edit', { defaultValue: 'Edit' })}
                      >
                        <Pencil size={14} />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => void handleDelete(visit)}
                        title={t('common.delete', { defaultValue: 'Delete' })}
                      >
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          )}

          {selectedVisit && (
            <VisitDetail visit={selectedVisit} onClose={() => setSelectedVisitId(null)} />
          )}
        </>
      )}

      {showCreateModal && (
        <VisitFormModal
          onClose={() => setShowCreateModal(false)}
          isPending={createMut.isPending}
          onSubmit={handleCreateSubmit}
        />
      )}

      {editingVisit && (
        <VisitFormModal
          isEdit
          initialData={visitFormData(editingVisit)}
          onClose={() => setEditingVisit(null)}
          isPending={updateMut.isPending}
          onSubmit={handleEditSubmit}
        />
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

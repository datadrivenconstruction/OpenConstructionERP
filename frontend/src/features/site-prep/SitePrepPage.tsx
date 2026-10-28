// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  ShieldCheck,
  ShieldAlert,
  Shield,
  CalendarClock,
  Gauge,
  Flag,
  Plus,
  Pencil,
  Trash2,
  X,
  AlertTriangle,
  ListChecks,
  CircleCheck,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  ConfirmDialog,
  RecoveryCard,
  SkeletonTable,
  Skeleton,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { getErrorMessage } from '@/shared/lib/api';
import { onlyChangedFields } from '@/shared/lib/apiHelpers';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchPlan,
  createPlan,
  updatePlan,
  fetchItems,
  createItem,
  updateItem,
  deleteItem,
  fetchReadiness,
  fetchGateStatus,
  SITE_PREP_CATEGORIES,
  SITE_PREP_ITEM_STATUSES,
  SITE_PREP_PLAN_STATUSES,
  type SitePrepCategory,
  type SitePrepItemStatus,
  type SitePrepPlanStatus,
  type SitePrepItem,
  type SitePrepItemPayload,
  type SitePrepItemUpdate,
  type SitePrepPlan,
  type SitePrepPlanPayload,
  type CategoryReadiness,
  type ReadinessReport,
  type GateStatus,
} from './api';
import { mobilisationGateState, type MobilisationGateState } from './mobilisationGate';

/* -- Vocabulary labels ----------------------------------------------------- */

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

const CATEGORY_DEFAULTS: Record<SitePrepCategory, string> = {
  access: 'Access',
  accommodation_welfare: 'Accommodation & welfare',
  temporary_utilities: 'Temporary utilities',
  security_hoarding: 'Security & hoarding',
  temporary_works: 'Temporary works',
  environmental_controls: 'Environmental controls',
  logistics_laydown: 'Logistics & laydown',
  permits_consents: 'Permits & consents',
  inductions_training: 'Inductions & training',
  other: 'Other',
};

const STATUS_DEFAULTS: Record<SitePrepItemStatus, string> = {
  not_started: 'Not started',
  in_progress: 'In progress',
  ready: 'Ready',
  blocked: 'Blocked',
  not_applicable: 'Not applicable',
};

const STATUS_VARIANT: Record<SitePrepItemStatus, BadgeVariant> = {
  not_started: 'neutral',
  in_progress: 'blue',
  ready: 'success',
  blocked: 'error',
  not_applicable: 'neutral',
};

const PLAN_STATUS_DEFAULTS: Record<SitePrepPlanStatus, string> = {
  draft: 'Draft',
  active: 'Active',
  complete: 'Complete',
};

const PLAN_STATUS_VARIANT: Record<SitePrepPlanStatus, BadgeVariant> = {
  draft: 'neutral',
  active: 'blue',
  complete: 'success',
};

type Translate = (key: string, options?: Record<string, unknown>) => string;

function categoryLabel(t: Translate, cat: string): string {
  const known = (SITE_PREP_CATEGORIES as readonly string[]).includes(cat);
  const fallback = known ? CATEGORY_DEFAULTS[cat as SitePrepCategory] : cat;
  return t(`site_prep.category_${cat}`, { defaultValue: fallback });
}

function statusLabel(t: Translate, status: string): string {
  const known = (SITE_PREP_ITEM_STATUSES as readonly string[]).includes(status);
  const fallback = known ? STATUS_DEFAULTS[status as SitePrepItemStatus] : status;
  return t(`site_prep.status_${status}`, { defaultValue: fallback });
}

function statusVariant(status: string): BadgeVariant {
  return (SITE_PREP_ITEM_STATUSES as readonly string[]).includes(status)
    ? STATUS_VARIANT[status as SitePrepItemStatus]
    : 'neutral';
}

function formatPct(t: Translate, pct: number | null | undefined): string {
  if (pct == null) return t('site_prep.value_na', { defaultValue: 'n/a' });
  return `${Math.round(pct)}%`;
}

function daysLabel(t: Translate, days: number | null | undefined): string {
  if (days == null) return t('site_prep.no_target_date', { defaultValue: 'No target date' });
  if (days === 0) return t('site_prep.starts_today', { defaultValue: 'Starts today' });
  if (days > 0) return t('site_prep.days_to_start', { defaultValue: '{{count}} days to start', count: days });
  return t('site_prep.days_overdue', { defaultValue: '{{count}} days overdue', count: Math.abs(days) });
}

/* -- Shared styles --------------------------------------------------------- */

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

/* -- Signal banner --------------------------------------------------------- */

// Three states, not two. `undetermined` is a project whose gates are unknown
// or undefined: it is neither a pass nor a failure, and painting it as either
// is a claim the data does not support.
const GATE_CARD_CLS: Record<MobilisationGateState, string> = {
  ready: 'border-semantic-success/40 bg-semantic-success-bg/40',
  blocked: 'border-semantic-error/40 bg-semantic-error-bg/40',
  undetermined: 'border-border bg-surface-secondary/40',
};

const GATE_MEDALLION_CLS: Record<MobilisationGateState, string> = {
  ready: 'bg-semantic-success/15 text-semantic-success',
  blocked: 'bg-semantic-error/15 text-semantic-error',
  undetermined: 'bg-surface-secondary text-content-tertiary',
};

const GATE_BADGE_VARIANT: Record<MobilisationGateState, BadgeVariant> = {
  ready: 'success',
  blocked: 'error',
  undetermined: 'neutral',
};

const GATE_ICON: Record<MobilisationGateState, typeof ShieldCheck> = {
  ready: ShieldCheck,
  blocked: ShieldAlert,
  undetermined: Shield,
};

/** Title, badge and description the banner prints for each gate state. */
function gateCopy(t: Translate, state: MobilisationGateState): { title: string; badge: string; desc: string } {
  if (state === 'ready') {
    return {
      title: t('site_prep.gate_ready_title', { defaultValue: 'Ready to mobilise' }),
      badge: t('site_prep.gate_ready_badge', { defaultValue: 'Gate open' }),
      desc: t('site_prep.gate_ready_desc', {
        defaultValue: 'All commencement gates are satisfied. The site can be mobilised.',
      }),
    };
  }
  if (state === 'blocked') {
    return {
      title: t('site_prep.gate_blocked_title', { defaultValue: 'Not ready to mobilise' }),
      badge: t('site_prep.gate_blocked_badge', { defaultValue: 'Gate closed' }),
      desc: t('site_prep.gate_blocked_desc', {
        defaultValue: 'Some commencement gates are still open. Clear them before starting on site.',
      }),
    };
  }
  return {
    title: t('site_prep.gate_unknown_title', { defaultValue: 'Mobilisation readiness not established' }),
    badge: t('site_prep.gate_unknown_badge', { defaultValue: 'No gates set' }),
    desc: t('site_prep.gate_unknown_desc', {
      defaultValue:
        'No commencement gates have been defined for this project, so there is nothing to clear yet. Add the readiness items this start depends on to see whether the site can be mobilised.',
    }),
  };
}

function MetricTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-elevated/80 px-3 py-2">
      <p className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">{label}</p>
      <p className="mt-0.5 text-sm font-semibold tabular-nums text-content-primary">{value}</p>
    </div>
  );
}

function SignalBanner({
  readiness,
  gate,
}: {
  readiness: ReadinessReport | undefined;
  gate: GateStatus | undefined;
}) {
  const { t } = useTranslation();
  const gateState = mobilisationGateState(readiness, gate);
  const onTrack = readiness?.on_track ?? gate?.on_track ?? true;
  const days = readiness?.days_to_target ?? gate?.days_to_target ?? null;
  const gateTotal = gate?.gate_total ?? readiness?.overall.gate_total ?? 0;
  const gateReadyCount = gate?.gate_ready_count ?? 0;
  const blockers = gate?.gate_blocking ?? [];

  const copy = gateCopy(t, gateState);
  const GateIcon = GATE_ICON[gateState];

  return (
    <Card padding="lg" className={clsx('border', GATE_CARD_CLS[gateState])}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-4">
          <div
            className={clsx(
              'flex h-14 w-14 shrink-0 items-center justify-center rounded-full',
              GATE_MEDALLION_CLS[gateState],
            )}
          >
            <GateIcon size={28} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-content-primary">{copy.title}</h2>
              <Badge variant={GATE_BADGE_VARIANT[gateState]} dot>
                {copy.badge}
              </Badge>
            </div>
            <p className="mt-1 max-w-xl text-sm text-content-secondary">{copy.desc}</p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:w-auto">
          <MetricTile
            label={t('site_prep.metric_readiness', { defaultValue: 'Overall readiness' })}
            value={formatPct(t, readiness?.readiness_percent)}
          />
          <MetricTile
            label={t('site_prep.metric_gates', { defaultValue: 'Gates cleared' })}
            value={t('site_prep.gate_count', {
              defaultValue: '{{ready}} of {{total}}',
              ready: gateReadyCount,
              total: gateTotal,
            })}
          />
          <MetricTile
            label={t('site_prep.metric_days', { defaultValue: 'Time to start' })}
            value={daysLabel(t, days)}
          />
          <MetricTile
            label={t('site_prep.metric_on_track', { defaultValue: 'Schedule' })}
            value={
              onTrack
                ? t('site_prep.on_track', { defaultValue: 'On track' })
                : t('site_prep.at_risk', { defaultValue: 'At risk' })
            }
          />
        </div>
      </div>

      {gateState === 'blocked' && blockers.length > 0 && (
        <div className="mt-4 rounded-lg border border-semantic-error/30 bg-surface-elevated/70 p-3">
          <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-semantic-error">
            <AlertTriangle size={13} />
            {t('site_prep.blockers_title', { defaultValue: 'Commencement gates still blocking' })}
          </p>
          <ul className="flex flex-col gap-1.5">
            {blockers.map((b, i) => (
              <li
                key={b.item_id ?? `${b.category}-${i}`}
                className="flex flex-wrap items-center gap-2 text-sm text-content-primary"
              >
                <Flag size={13} className="shrink-0 text-semantic-error" />
                <span className="min-w-0 truncate">{b.title}</span>
                <Badge variant="neutral" size="sm">
                  {categoryLabel(t, b.category)}
                </Badge>
                <Badge variant={statusVariant(b.status)} size="sm">
                  {statusLabel(t, b.status)}
                </Badge>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

/* -- Category grid --------------------------------------------------------- */

function CategoryCard({
  category,
  data,
}: {
  category: SitePrepCategory;
  data: CategoryReadiness | undefined;
}) {
  const { t } = useTranslation();
  const total = data?.total ?? 0;
  const ready = data?.ready ?? 0;
  const pct = data?.readiness_percent ?? null;
  const blocked = data?.blocked ?? 0;
  const overdue = data?.overdue ?? 0;

  return (
    <Card padding="sm" className="flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium leading-tight text-content-primary">
          {categoryLabel(t, category)}
        </p>
        <span className="text-sm font-semibold tabular-nums text-content-secondary">
          {formatPct(t, pct)}
        </span>
      </div>

      <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary">
        <div
          className={clsx('h-full rounded-full', blocked > 0 ? 'bg-semantic-warning' : 'bg-oe-blue')}
          style={{ width: `${pct ?? 0}%` }}
        />
      </div>

      <p className="text-2xs text-content-tertiary">
        {total === 0
          ? t('site_prep.cat_no_items', { defaultValue: 'No items' })
          : t('site_prep.cat_ready_of_total', {
              defaultValue: '{{ready}} of {{total}} ready',
              ready,
              total,
            })}
      </p>

      {(blocked > 0 || overdue > 0) && (
        <div className="flex flex-wrap gap-1.5">
          {blocked > 0 && (
            <Badge variant="error" size="sm">
              {t('site_prep.cat_blocked', { defaultValue: '{{count}} blocked', count: blocked })}
            </Badge>
          )}
          {overdue > 0 && (
            <Badge variant="warning" size="sm">
              {t('site_prep.cat_overdue', { defaultValue: '{{count}} overdue', count: overdue })}
            </Badge>
          )}
        </div>
      )}
    </Card>
  );
}

/* -- Item row -------------------------------------------------------------- */

function ItemRow({
  item,
  onEdit,
  onDelete,
}: {
  item: SitePrepItem;
  onEdit: (item: SitePrepItem) => void;
  onDelete: (item: SitePrepItem) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-border-light px-4 py-3 last:border-b-0 hover:bg-surface-secondary/40">
      {item.is_gate ? (
        <Flag
          size={15}
          className="shrink-0 text-oe-blue"
          aria-label={t('site_prep.gate_flag_title', {
            defaultValue: 'Commencement gate: a hard prerequisite to start on site',
          })}
        />
      ) : (
        <span className="w-[15px] shrink-0" aria-hidden />
      )}

      <span className="min-w-0 flex-1 basis-48 truncate text-sm text-content-primary">
        {item.title}
        {item.is_gate && (
          <Badge variant="blue" size="sm" className="ml-2 align-middle">
            {t('site_prep.gate_flag', { defaultValue: 'Gate' })}
          </Badge>
        )}
      </span>

      <Badge variant="neutral" size="sm">
        {categoryLabel(t, item.category)}
      </Badge>

      <Badge variant={statusVariant(item.status)} size="sm">
        {statusLabel(t, item.status)}
      </Badge>

      <span className="hidden w-40 truncate text-xs text-content-tertiary md:block">
        {item.responsible_party
          ? item.responsible_party
          : t('site_prep.no_responsible', { defaultValue: 'Unassigned' })}
      </span>

      <span className="w-24 text-right text-xs text-content-tertiary">
        {item.due_date ? (
          <DateDisplay value={item.due_date} />
        ) : (
          t('site_prep.no_due_date', { defaultValue: 'No due date' })
        )}
      </span>

      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onEdit(item)}
          icon={<Pencil size={13} />}
          aria-label={t('site_prep.edit_item', { defaultValue: 'Edit item' })}
          title={t('site_prep.edit_item', { defaultValue: 'Edit item' })}
        />
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onDelete(item)}
          icon={<Trash2 size={13} />}
          className="text-semantic-error"
          aria-label={t('site_prep.delete_item', { defaultValue: 'Delete item' })}
          title={t('site_prep.delete_item', { defaultValue: 'Delete item' })}
        />
      </div>
    </div>
  );
}

/* -- Item modal (create + edit) -------------------------------------------- */

interface ItemFormState {
  category: SitePrepCategory;
  title: string;
  description: string;
  status: SitePrepItemStatus;
  responsible_party: string;
  due_date: string;
  is_gate: boolean;
  notes: string;
}

function toForm(item: SitePrepItem | null): ItemFormState {
  return {
    category: (SITE_PREP_CATEGORIES as readonly string[]).includes(item?.category ?? '')
      ? (item?.category as SitePrepCategory)
      : 'access',
    title: item?.title ?? '',
    description: item?.description ?? '',
    status: (SITE_PREP_ITEM_STATUSES as readonly string[]).includes(item?.status ?? '')
      ? (item?.status as SitePrepItemStatus)
      : 'not_started',
    responsible_party: item?.responsible_party ?? '',
    due_date: item?.due_date ?? '',
    is_gate: item?.is_gate ?? false,
    notes: item?.notes ?? '',
  };
}

function ItemModal({
  initial,
  onClose,
  onSubmit,
  isPending,
}: {
  initial: SitePrepItem | null;
  onClose: () => void;
  /** A whole `SitePrepItemPayload` when creating; only the changed fields on edit. */
  onSubmit: (payload: SitePrepItemPayload | SitePrepItemUpdate) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  // The state the form opened with, kept so the save can send only what the
  // user actually changed. Writing the whole form back on every save rewrites
  // fields nobody opened with the values they held when this list was last
  // read, undoing anyone else's edit to them without a word. The update route
  // dumps with `exclude_unset=True`, so an omitted field is left alone.
  const base = useMemo(() => toForm(initial), [initial]);
  const [form, setForm] = useState<ItemFormState>(base);
  const [touched, setTouched] = useState(false);
  const isEdit = initial !== null;

  const set = <K extends keyof ItemFormState>(key: K, value: ItemFormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const titleError = touched && form.title.trim().length === 0;
  const canSubmit = form.title.trim().length > 0;

  const handleSubmit = () => {
    setTouched(true);
    if (!canSubmit) return;
    const payload: SitePrepItemPayload = {
      category: form.category,
      title: form.title.trim(),
      description: form.description.trim() || null,
      status: form.status,
      responsible_party: form.responsible_party.trim() || null,
      due_date: form.due_date || null,
      is_gate: form.is_gate,
      notes: form.notes.trim() || null,
    };
    onSubmit(isEdit ? onlyChangedFields(payload, form, base) : payload);
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-lg animate-fade-in">
      <div
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-border bg-surface-elevated shadow-xl animate-card-in"
        role="dialog"
        aria-modal="true"
      >
        <div className="flex items-center justify-between border-b border-border-light px-6 py-4">
          <h2 className="text-lg font-semibold text-content-primary">
            {isEdit
              ? t('site_prep.edit_item_title', { defaultValue: 'Edit readiness item' })
              : t('site_prep.new_item_title', { defaultValue: 'New readiness item' })}
          </h2>
          <button
            onClick={onClose}
            aria-label={t('site_prep.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4 px-6 py-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-sm font-medium text-content-primary">
                {t('site_prep.field_category', { defaultValue: 'Category' })}
              </label>
              <select
                value={form.category}
                onChange={(e) => set('category', e.target.value as SitePrepCategory)}
                className={inputCls}
              >
                {SITE_PREP_CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {categoryLabel(t, c)}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-content-primary">
                {t('site_prep.field_status', { defaultValue: 'Status' })}
              </label>
              <select
                value={form.status}
                onChange={(e) => set('status', e.target.value as SitePrepItemStatus)}
                className={inputCls}
              >
                {SITE_PREP_ITEM_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {statusLabel(t, s)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-sm font-medium text-content-primary">
              {t('site_prep.field_title', { defaultValue: 'Title' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              value={form.title}
              autoFocus
              onChange={(e) => {
                set('title', e.target.value);
                setTouched(true);
              }}
              placeholder={t('site_prep.title_placeholder', {
                defaultValue: 'e.g. Site access road and gate installed',
              })}
              className={clsx(inputCls, titleError && 'border-semantic-error focus:ring-red-300')}
            />
            {titleError && (
              <p className="mt-1 text-xs text-semantic-error">
                {t('site_prep.title_required', { defaultValue: 'Title is required' })}
              </p>
            )}
          </div>

          <div>
            <label className="mb-1.5 block text-sm font-medium text-content-primary">
              {t('site_prep.field_description', { defaultValue: 'Description' })}
            </label>
            <textarea
              value={form.description}
              rows={3}
              onChange={(e) => set('description', e.target.value)}
              placeholder={t('site_prep.description_placeholder', {
                defaultValue: 'What needs to be in place, and how it is verified as ready',
              })}
              className={textareaCls}
            />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-sm font-medium text-content-primary">
                {t('site_prep.field_responsible', { defaultValue: 'Responsible party' })}
              </label>
              <input
                value={form.responsible_party}
                onChange={(e) => set('responsible_party', e.target.value)}
                placeholder={t('site_prep.responsible_placeholder', {
                  defaultValue: 'e.g. Site manager, groundworks subcontractor',
                })}
                className={inputCls}
              />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-content-primary">
                {t('site_prep.field_due_date', { defaultValue: 'Due date' })}
              </label>
              <input
                type="date"
                value={form.due_date}
                onChange={(e) => set('due_date', e.target.value)}
                className={inputCls}
              />
            </div>
          </div>

          <label className="flex items-center gap-2.5 rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2.5">
            <input
              type="checkbox"
              checked={form.is_gate}
              onChange={(e) => set('is_gate', e.target.checked)}
              className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
            />
            <span className="text-sm text-content-primary">
              {t('site_prep.field_is_gate', {
                defaultValue: 'This is a commencement gate (hard prerequisite to start)',
              })}
            </span>
          </label>

          <div>
            <label className="mb-1.5 block text-sm font-medium text-content-primary">
              {t('site_prep.field_notes', { defaultValue: 'Notes' })}
            </label>
            <textarea
              value={form.notes}
              rows={2}
              onChange={(e) => set('notes', e.target.value)}
              placeholder={t('site_prep.notes_placeholder', {
                defaultValue: 'Any dependencies, references or context',
              })}
              className={textareaCls}
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-border-light px-6 py-4">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('site_prep.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={handleSubmit}
            loading={isPending}
            disabled={!canSubmit}
            icon={!isPending ? <Plus size={15} /> : undefined}
          >
            {isEdit
              ? t('site_prep.save', { defaultValue: 'Save' })
              : t('site_prep.create', { defaultValue: 'Create item' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* -- Plan modal (create + edit) -------------------------------------------- */

interface PlanFormState {
  target_start_date: string;
  status: SitePrepPlanStatus;
  notes: string;
}

function ItemsCount({ count }: { count: number }) {
  const { t } = useTranslation();
  return (
    <p className="mb-3 text-sm text-content-tertiary">
      {t('site_prep.items_count', { defaultValue: '{{count}} items', count })}
    </p>
  );
}

function PlanModal({
  plan,
  onClose,
  onSubmit,
  isPending,
}: {
  plan: SitePrepPlan | null;
  onClose: () => void;
  onSubmit: (payload: SitePrepPlanPayload) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<PlanFormState>(() => ({
    target_start_date: plan?.target_start_date ?? '',
    status: (SITE_PREP_PLAN_STATUSES as readonly string[]).includes(plan?.status ?? '')
      ? (plan?.status as SitePrepPlanStatus)
      : 'draft',
    notes: plan?.notes ?? '',
  }));
  const isEdit = plan !== null;

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-lg animate-fade-in">
      <div
        className="w-full max-w-lg rounded-xl border border-border bg-surface-elevated shadow-xl animate-card-in"
        role="dialog"
        aria-modal="true"
      >
        <div className="flex items-center justify-between border-b border-border-light px-6 py-4">
          <h2 className="text-lg font-semibold text-content-primary">
            {isEdit
              ? t('site_prep.plan_modal_edit_title', { defaultValue: 'Edit mobilisation plan' })
              : t('site_prep.plan_modal_create_title', { defaultValue: 'Create mobilisation plan' })}
          </h2>
          <button
            onClick={onClose}
            aria-label={t('site_prep.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-4 px-6 py-4">
          <div>
            <label className="mb-1.5 block text-sm font-medium text-content-primary">
              {t('site_prep.field_target_start', { defaultValue: 'Target start date' })}
            </label>
            <input
              type="date"
              value={form.target_start_date}
              onChange={(e) => setForm((p) => ({ ...p, target_start_date: e.target.value }))}
              className={inputCls}
            />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium text-content-primary">
              {t('site_prep.field_plan_status', { defaultValue: 'Plan status' })}
            </label>
            <select
              value={form.status}
              onChange={(e) =>
                setForm((p) => ({ ...p, status: e.target.value as SitePrepPlanStatus }))
              }
              className={inputCls}
            >
              {SITE_PREP_PLAN_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {t(`site_prep.plan_status_${s}`, { defaultValue: PLAN_STATUS_DEFAULTS[s] })}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium text-content-primary">
              {t('site_prep.field_notes', { defaultValue: 'Notes' })}
            </label>
            <textarea
              value={form.notes}
              rows={3}
              onChange={(e) => setForm((p) => ({ ...p, notes: e.target.value }))}
              placeholder={t('site_prep.plan_notes_placeholder', {
                defaultValue: 'Scope of mobilisation, key dates, constraints',
              })}
              className={textareaCls}
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 border-t border-border-light px-6 py-4">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('site_prep.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            loading={isPending}
            onClick={() =>
              onSubmit({
                target_start_date: form.target_start_date || null,
                status: form.status,
                notes: form.notes.trim() || null,
              })
            }
          >
            {t('site_prep.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* -- Main page ------------------------------------------------------------- */

export function SitePrepPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = routeProjectId || activeProjectId || '';
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();

  const [categoryFilter, setCategoryFilter] = useState<SitePrepCategory | ''>('');
  const [statusFilter, setStatusFilter] = useState<SitePrepItemStatus | ''>('');
  const [showItemModal, setShowItemModal] = useState(false);
  const [editingItem, setEditingItem] = useState<SitePrepItem | null>(null);
  const [showPlanModal, setShowPlanModal] = useState(false);

  const planQuery = useQuery({
    queryKey: ['site-prep', 'plan', projectId],
    queryFn: () => fetchPlan(projectId),
    enabled: !!projectId,
  });

  const readinessQuery = useQuery({
    queryKey: ['site-prep', 'readiness', projectId],
    queryFn: () => fetchReadiness(projectId),
    enabled: !!projectId,
  });

  const gateQuery = useQuery({
    queryKey: ['site-prep', 'gate', projectId],
    queryFn: () => fetchGateStatus(projectId),
    enabled: !!projectId,
  });

  const itemsQuery = useQuery({
    queryKey: ['site-prep', 'items', projectId, categoryFilter, statusFilter],
    queryFn: () =>
      fetchItems(projectId, {
        category: categoryFilter || undefined,
        status: statusFilter || undefined,
      }),
    enabled: !!projectId,
  });

  const plan = planQuery.data ?? null;
  const readiness = readinessQuery.data;
  const gate = gateQuery.data;
  const items = useMemo(() => itemsQuery.data ?? [], [itemsQuery.data]);

  const categoryMap = useMemo(() => {
    const map = new Map<string, CategoryReadiness>();
    for (const c of readiness?.categories ?? []) map.set(c.category, c);
    return map;
  }, [readiness]);

  const invalidateAll = () => qc.invalidateQueries({ queryKey: ['site-prep'] });

  const errorToast = (e: unknown) =>
    addToast({
      type: 'error',
      title: t('site_prep.error', { defaultValue: 'Error' }),
      message: getErrorMessage(e),
    });

  const saveItemMut = useMutation({
    mutationFn: (payload: SitePrepItemPayload | SitePrepItemUpdate) =>
      editingItem
        ? updateItem(projectId, editingItem.id, payload)
        // Without an `editingItem` the modal never trims the payload, so this
        // branch always receives the whole `SitePrepItemPayload`.
        : createItem(projectId, payload as SitePrepItemPayload),
    onSuccess: () => {
      invalidateAll();
      setShowItemModal(false);
      setEditingItem(null);
      addToast({
        type: 'success',
        title: editingItem
          ? t('site_prep.item_updated', { defaultValue: 'Readiness item updated' })
          : t('site_prep.item_created', { defaultValue: 'Readiness item created' }),
      });
    },
    onError: errorToast,
  });

  const deleteItemMut = useMutation({
    mutationFn: (id: string) => deleteItem(projectId, id),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('site_prep.item_deleted', { defaultValue: 'Readiness item deleted' }),
      });
    },
    onError: errorToast,
  });

  const savePlanMut = useMutation({
    mutationFn: (payload: SitePrepPlanPayload) =>
      plan ? updatePlan(projectId, payload) : createPlan(projectId, payload),
    onSuccess: () => {
      invalidateAll();
      setShowPlanModal(false);
      addToast({
        type: 'success',
        title: t('site_prep.plan_saved', { defaultValue: 'Mobilisation plan saved' }),
      });
    },
    onError: errorToast,
  });

  const openCreate = () => {
    setEditingItem(null);
    setShowItemModal(true);
  };
  const openEdit = (item: SitePrepItem) => {
    setEditingItem(item);
    setShowItemModal(true);
  };
  const handleDelete = async (item: SitePrepItem) => {
    const ok = await confirm({
      title: t('site_prep.confirm_delete_title', { defaultValue: 'Delete readiness item?' }),
      message: t('site_prep.confirm_delete_msg', {
        defaultValue: 'This mobilisation readiness item will be permanently removed.',
      }),
      confirmLabel: t('site_prep.delete_item', { defaultValue: 'Delete item' }),
      variant: 'danger',
    });
    if (ok) deleteItemMut.mutate(item.id);
  };

  const planStatus = (SITE_PREP_PLAN_STATUSES as readonly string[]).includes(plan?.status ?? '')
    ? (plan?.status as SitePrepPlanStatus)
    : null;

  return (
    <div className="animate-fade-in space-y-5">
      <PageHeader
        srTitle={t('site_prep.title', { defaultValue: 'Site prep' })}
        subtitle={t('site_prep.subtitle', {
          defaultValue:
            'Track pre-construction mobilisation readiness and the gate to start on site',
        })}
        actions={
          <>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setShowPlanModal(true)}
              disabled={!projectId}
              icon={<CalendarClock size={14} />}
            >
              {plan
                ? t('site_prep.edit_plan', { defaultValue: 'Edit plan' })
                : t('site_prep.create_plan', { defaultValue: 'Create plan' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={openCreate}
              disabled={!projectId}
              icon={<Plus size={14} />}
            >
              {t('site_prep.new_item', { defaultValue: 'New readiness item' })}
            </Button>
          </>
        }
      />

      <RequiresProject
        emptyHint={t('site_prep.select_project', {
          defaultValue: 'Open a project first to view and manage site mobilisation readiness.',
        })}
      >
        {/* Plan strip */}
        <div className="flex flex-wrap items-center gap-2 text-sm text-content-secondary">
          <CalendarClock size={15} className="text-content-tertiary" />
          {plan ? (
            <>
              <span className="text-content-tertiary">
                {t('site_prep.plan_target', { defaultValue: 'Target start' })}:
              </span>
              {plan.target_start_date ? (
                <span className="font-medium text-content-primary">
                  <DateDisplay value={plan.target_start_date} />
                </span>
              ) : (
                <span className="text-content-tertiary">
                  {t('site_prep.no_target_date', { defaultValue: 'No target date' })}
                </span>
              )}
              {planStatus && (
                <Badge variant={PLAN_STATUS_VARIANT[planStatus]} size="sm">
                  {t(`site_prep.plan_status_${planStatus}`, {
                    defaultValue: PLAN_STATUS_DEFAULTS[planStatus],
                  })}
                </Badge>
              )}
            </>
          ) : (
            <span className="text-content-tertiary">
              {t('site_prep.no_plan', { defaultValue: 'No mobilisation plan yet' })}
            </span>
          )}
        </div>

        {/* Signal banner */}
        {readinessQuery.isLoading ? (
          <Skeleton className="h-32 w-full rounded-xl" />
        ) : readinessQuery.isError ? (
          <RecoveryCard error={readinessQuery.error} onRetry={() => readinessQuery.refetch()} />
        ) : (
          <SignalBanner readiness={readiness} gate={gate} />
        )}

        {/* Category grid */}
        <div>
          <h2 className="mb-3 flex items-center gap-1.5 text-sm font-semibold text-content-primary">
            <Gauge size={15} className="text-oe-blue" />
            {t('site_prep.categories_title', { defaultValue: 'Readiness by category' })}
          </h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {SITE_PREP_CATEGORIES.map((c) => (
              <CategoryCard key={c} category={c} data={categoryMap.get(c)} />
            ))}
          </div>
        </div>

        {/* Items */}
        <div>
          <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <h2 className="flex items-center gap-1.5 text-sm font-semibold text-content-primary">
              <ListChecks size={15} className="text-oe-blue" />
              {t('site_prep.items_title', { defaultValue: 'Readiness items' })}
            </h2>
            <div className="flex flex-wrap gap-2">
              <select
                value={categoryFilter}
                onChange={(e) => setCategoryFilter(e.target.value as SitePrepCategory | '')}
                aria-label={t('site_prep.filter_all_categories', { defaultValue: 'All categories' })}
                className={inputCls + ' sm:w-52'}
              >
                <option value="">
                  {t('site_prep.filter_all_categories', { defaultValue: 'All categories' })}
                </option>
                {SITE_PREP_CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {categoryLabel(t, c)}
                  </option>
                ))}
              </select>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as SitePrepItemStatus | '')}
                aria-label={t('site_prep.filter_all_statuses', { defaultValue: 'All statuses' })}
                className={inputCls + ' sm:w-44'}
              >
                <option value="">
                  {t('site_prep.filter_all_statuses', { defaultValue: 'All statuses' })}
                </option>
                {SITE_PREP_ITEM_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {statusLabel(t, s)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {itemsQuery.isLoading ? (
            <SkeletonTable rows={5} columns={5} />
          ) : itemsQuery.isError ? (
            <RecoveryCard error={itemsQuery.error} onRetry={() => itemsQuery.refetch()} />
          ) : items.length === 0 ? (
            <EmptyState
              icon={<CircleCheck size={28} strokeWidth={1.5} />}
              title={
                categoryFilter || statusFilter
                  ? t('site_prep.no_results', { defaultValue: 'No matching items' })
                  : t('site_prep.no_items', { defaultValue: 'No readiness items yet' })
              }
              description={
                categoryFilter || statusFilter
                  ? t('site_prep.no_results_hint', {
                      defaultValue: 'Try a different category or status filter.',
                    })
                  : t('site_prep.no_items_hint', {
                      defaultValue:
                        'Add the first mobilisation task the site needs before work can start.',
                    })
              }
              action={
                !categoryFilter && !statusFilter
                  ? {
                      label: t('site_prep.new_item', { defaultValue: 'New readiness item' }),
                      onClick: openCreate,
                    }
                  : undefined
              }
            />
          ) : (
            <>
              <ItemsCount count={items.length} />
              <Card padding="none" className="overflow-hidden">
                <div className="flex flex-wrap items-center gap-3 border-b border-border-light bg-surface-secondary/30 px-4 py-2.5 text-2xs font-medium uppercase tracking-wider text-content-tertiary">
                  <span className="w-[15px]" aria-hidden />
                  <span className="flex-1 basis-48">
                    {t('site_prep.col_item', { defaultValue: 'Item' })}
                  </span>
                  <span className="w-28 text-center">
                    {t('site_prep.field_category', { defaultValue: 'Category' })}
                  </span>
                  <span className="w-24 text-center">
                    {t('site_prep.field_status', { defaultValue: 'Status' })}
                  </span>
                  <span className="hidden w-40 md:block">
                    {t('site_prep.responsible_label', { defaultValue: 'Responsible' })}
                  </span>
                  <span className="w-24 text-right">
                    {t('site_prep.due_label', { defaultValue: 'Due' })}
                  </span>
                  <span className="w-16" aria-hidden />
                </div>
                {items.map((item) => (
                  <ItemRow key={item.id} item={item} onEdit={openEdit} onDelete={handleDelete} />
                ))}
              </Card>
            </>
          )}
        </div>
      </RequiresProject>

      {showItemModal && (
        <ItemModal
          initial={editingItem}
          onClose={() => {
            setShowItemModal(false);
            setEditingItem(null);
          }}
          onSubmit={(payload) => saveItemMut.mutate(payload)}
          isPending={saveItemMut.isPending}
        />
      )}

      {showPlanModal && (
        <PlanModal
          plan={plan}
          onClose={() => setShowPlanModal(false)}
          onSubmit={(payload) => savePlanMut.mutate(payload)}
          isPending={savePlanMut.isPending}
        />
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

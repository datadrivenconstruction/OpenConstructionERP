// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Management of Change (MoC) page.
 *
 * A structured change-control register: propose a change, assess its cost /
 * schedule / risk impact, then walk it through review and approval before it
 * is implemented. The status flow is enforced by the backend FSM
 * (proposed -> reviewed -> accepted | declined -> implemented); this page
 * only ever offers the transitions that are legal for the current state.
 */

import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate } from 'react-router-dom';
import { changeOrderDeepLink, linkedVariationDeepLink } from '@/shared/lib/changeChainLinks';
import clsx from 'clsx';
import {
  Replace,
  Plus,
  X,
  Search,
  ChevronDown,
  ChevronRight,
  Wrench,
  PenTool,
  Package,
  ShieldAlert,
  Users,
  Scale,
  Workflow,
  Maximize2,
  MoreHorizontal,
  DollarSign,
  CalendarClock,
  CheckCircle2,
  XCircle,
  ClipboardCheck,
  Rocket,
  Link2,
  Trash2,
  Pencil,
  ListPlus,
  ShieldCheck,
  Wallet,
  Download,
  ArrowUpDown,
  RotateCcw,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  ConfirmDialog,
  RecoveryCard,
  SkeletonTable,
  IntroRichText,
  ModuleGuideButton,
  InfoHint,
} from '@/shared/ui';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { PageHeader } from '@/shared/ui/PageHeader';
import { SectionIntro } from '@/features/validation';
import { ProvabilityGauge, EvidenceThreadPanel } from '@/features/claims-evidence';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { apiGet } from '@/shared/lib/api';
import { onlyChangedFields } from '@/shared/lib/apiHelpers';
import { toNum, formatCurrency } from '@/shared/lib/money';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchMoCEntries,
  createMoCEntry,
  updateMoCEntry,
  deleteMoCEntry,
  transitionMoCEntry,
  addMoCImpact,
  deleteMoCImpact,
  type MoCEntry,
  type MoCStatus,
  type MoCTransition,
  type MoCChangeCategory,
  type MoCRiskLevel,
  type CreateMoCPayload,
  type UpdateMoCPayload,
  type CreateImpactPayload,
} from './api';
import { mocGuide } from './mocGuide';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import { buildMocInsights } from './mocInsights';
import { toDecimalPayloadString } from '@/shared/lib/parseDecimal';
import { getNumberLocale } from '@/stores/usePreferencesStore';

// English fallbacks for the computed `moc.action_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const MOC_ACTION_LABELS: Record<string, string> = {
  review: 'Review', accept: 'Accept', decline: 'Decline', implement: 'Implement'
};

// English fallbacks for the computed `moc.status_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const MOC_STATUS_LABELS: Record<string, string> = {
  proposed: 'Proposed', reviewed: 'Reviewed', accepted: 'Accepted', declined: 'Declined',
  implemented: 'Implemented'
};


// English fallbacks for the computed `moc.category_*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const MOC_CATEGORY_LABELS: Record<string, string> = {
  engineering: 'Engineering', scope: 'Scope', design: 'Design', process: 'Process', material: 'Material',
  safety: 'Safety', organizational: 'Organisational', regulatory: 'Regulatory', other: 'Other'
};


/* -- Constants ------------------------------------------------------------- */

interface Project {
  id: string;
  name: string;
}

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'error' | 'warning';

const CATEGORIES: MoCChangeCategory[] = [
  'engineering',
  'scope',
  'design',
  'process',
  'material',
  'safety',
  'organizational',
  'regulatory',
  'other',
];

const CATEGORY_CONFIG: Record<
  MoCChangeCategory,
  { icon: React.ElementType; color: string }
> = {
  engineering: { icon: Wrench, color: 'text-blue-600 bg-blue-50 border-blue-200 dark:text-blue-400 dark:bg-blue-950/30 dark:border-blue-800' },
  scope: { icon: Maximize2, color: 'text-indigo-600 bg-indigo-50 border-indigo-200 dark:text-indigo-400 dark:bg-indigo-950/30 dark:border-indigo-800' },
  design: { icon: PenTool, color: 'text-purple-600 bg-purple-50 border-purple-200 dark:text-purple-400 dark:bg-purple-950/30 dark:border-purple-800' },
  process: { icon: Workflow, color: 'text-cyan-600 bg-cyan-50 border-cyan-200 dark:text-cyan-400 dark:bg-cyan-950/30 dark:border-cyan-800' },
  material: { icon: Package, color: 'text-amber-600 bg-amber-50 border-amber-200 dark:text-amber-400 dark:bg-amber-950/30 dark:border-amber-800' },
  safety: { icon: ShieldAlert, color: 'text-red-600 bg-red-50 border-red-200 dark:text-red-400 dark:bg-red-950/30 dark:border-red-800' },
  organizational: { icon: Users, color: 'text-teal-600 bg-teal-50 border-teal-200 dark:text-teal-400 dark:bg-teal-950/30 dark:border-teal-800' },
  regulatory: { icon: Scale, color: 'text-rose-600 bg-rose-50 border-rose-200 dark:text-rose-400 dark:bg-rose-950/30 dark:border-rose-800' },
  other: { icon: MoreHorizontal, color: 'text-gray-600 bg-gray-50 border-gray-200 dark:text-gray-400 dark:bg-gray-800/50 dark:border-gray-700' },
};

const RISK_LEVELS: MoCRiskLevel[] = ['low', 'medium', 'high', 'critical'];

const RISK_CONFIG: Record<MoCRiskLevel, { variant: BadgeVariant; cls: string }> = {
  low: { variant: 'neutral', cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' },
  medium: { variant: 'warning', cls: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300' },
  high: { variant: 'warning', cls: 'bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300' },
  critical: { variant: 'error', cls: '' },
};

const STATUS_FLOW: MoCStatus[] = [
  'proposed',
  'reviewed',
  'accepted',
  'declined',
  'implemented',
];

const STATUS_CONFIG: Record<MoCStatus, { variant: BadgeVariant; cls: string }> = {
  proposed: { variant: 'blue', cls: '' },
  reviewed: { variant: 'warning', cls: '' },
  accepted: { variant: 'success', cls: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300' },
  declined: { variant: 'neutral', cls: 'bg-gray-200 text-gray-600 line-through dark:bg-gray-700 dark:text-gray-400' },
  implemented: { variant: 'success', cls: '' },
};

/** Which transition verbs are legal from each state (drives the buttons). */
const NEXT_TRANSITIONS: Record<MoCStatus, MoCTransition[]> = {
  proposed: ['review'],
  reviewed: ['accept', 'decline'],
  accepted: ['implement'],
  declined: [],
  implemented: [],
};

const TRANSITION_CONFIG: Record<
  MoCTransition,
  { icon: React.ElementType; variant: 'primary' | 'secondary' | 'danger' | 'ghost'; notesLabel: string }
> = {
  review: { icon: ClipboardCheck, variant: 'primary', notesLabel: 'Review notes' },
  accept: { icon: CheckCircle2, variant: 'primary', notesLabel: 'Decision notes' },
  decline: { icon: XCircle, variant: 'danger', notesLabel: 'Reason for declining' },
  implement: { icon: Rocket, variant: 'primary', notesLabel: 'Implementation notes' },
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function formatMoney(amount: string | null | undefined, currency: string): string {
  const n = Number.parseFloat(amount || '0');
  if (!Number.isFinite(n) || n === 0) return '';
  const formatted = n.toLocaleString(getNumberLocale(), { maximumFractionDigits: 2 });
  return currency ? `${currency} ${formatted}` : formatted;
}

/** Signed integer for schedule deltas: "+5", "0", "-3". */
function signed(n: number): string {
  return n > 0 ? `+${n}` : String(n);
}

const selectCls =
  'h-10 appearance-none rounded-lg border border-border bg-surface-primary pl-3 pr-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue';

/* -- Cost / schedule exposure rollup + register sorting -------------------- */

/** Weight used to surface the highest-risk changes first. */
const RISK_RANK: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 };

/** Register sort modes. `default` keeps the order the backend returned. */
type MoCSortMode = 'default' | 'cost' | 'risk' | 'schedule';

const SORT_OPTIONS: { mode: MoCSortMode; labelKey: string; labelDefault: string }[] = [
  { mode: 'default', labelKey: 'moc.sort_default', labelDefault: 'Default order' },
  { mode: 'cost', labelKey: 'moc.sort_cost', labelDefault: 'Largest cost impact' },
  { mode: 'risk', labelKey: 'moc.sort_risk', labelDefault: 'Highest risk' },
  { mode: 'schedule', labelKey: 'moc.sort_schedule', labelDefault: 'Largest schedule impact' },
];

/**
 * Exposure buckets by lifecycle stage. `declined` is deliberately excluded:
 * a rejected change carries no committed cost or programme exposure.
 *   pending     = proposed + reviewed (potential, still under review)
 *   accepted    = approved but NOT yet implemented (the live exposure)
 *   implemented = already carried out (realized)
 */
type ExposureBucket = 'pending' | 'accepted' | 'implemented';

interface CurrencyExposure {
  /** Normalised ISO-ish code; '' means the entry left currency blank. */
  currency: string;
  cost: Record<ExposureBucket, number>;
  days: Record<ExposureBucket, number>;
  count: Record<ExposureBucket, number>;
}

const EXPOSURE_BUCKETS: {
  key: ExposureBucket;
  labelKey: string;
  labelDefault: string;
  accent: string;
  emphasized?: boolean;
}[] = [
  {
    key: 'pending',
    labelKey: 'moc.exposure_pending',
    labelDefault: 'Under review',
    accent: 'border-border-light bg-surface-secondary/40',
  },
  {
    key: 'accepted',
    labelKey: 'moc.exposure_committed',
    labelDefault: 'Committed (accepted)',
    accent:
      'border-amber-300 bg-amber-50 ring-1 ring-amber-300/40 dark:border-amber-800 dark:bg-amber-950/30 dark:ring-amber-700/40',
    emphasized: true,
  },
  {
    key: 'implemented',
    labelKey: 'moc.exposure_realized',
    labelDefault: 'Realized (implemented)',
    accent: 'border-emerald-200 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/20',
  },
];

/**
 * Cost and schedule exposure band.
 *
 * Sums the headline cost_impact (a Decimal string, coerced via `toNum`) and
 * schedule_delta_days on the currently-visible entries, split by lifecycle
 * bucket and grouped by currency so amounts in different currencies are never
 * blended into one total. Answers the question the count cards cannot: how
 * much accepted-but-not-yet-implemented change is the project carrying.
 */
function MoCExposureBand({
  rows,
  declinedCount,
}: {
  rows: CurrencyExposure[];
  declinedCount: number;
}) {
  const { t } = useTranslation();
  const multi = rows.length > 1;

  return (
    <Card padding="none" className="overflow-hidden animate-card-in">
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-border-light bg-surface-secondary/30">
        <div className="flex items-center gap-2 min-w-0">
          <Wallet size={15} className="text-content-tertiary shrink-0" />
          <span className="text-sm font-semibold text-content-primary">
            {t('moc.exposure_title', { defaultValue: 'Cost and schedule exposure' })}
          </span>
          <InfoHint
            inline
            text={t('moc.exposure_hint', {
              defaultValue:
                'Under review is potential exposure from proposed and reviewed changes. Committed is accepted change, approved but not yet implemented, which is your live exposure. Realized is change already implemented. Declined changes are excluded, and each currency is totalled separately.',
            })}
          />
        </div>
        {multi && (
          <span className="text-2xs text-content-tertiary shrink-0 tabular-nums">
            {t('moc.exposure_currencies', {
              defaultValue: '{{count}} currencies',
              count: rows.length,
            })}
          </span>
        )}
      </div>

      <div className="divide-y divide-border-light">
        {rows.map((row) => (
          <div key={row.currency || '__unspecified__'} className="px-4 py-3">
            <div className="mb-2.5 flex items-center gap-2">
              <Badge variant="neutral" size="sm" className="font-mono uppercase">
                {row.currency || t('moc.currency_unspecified', { defaultValue: 'Unspecified' })}
              </Badge>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
              {EXPOSURE_BUCKETS.map((b) => {
                const cost = row.cost[b.key];
                const days = row.days[b.key];
                const count = row.count[b.key];
                return (
                  <div key={b.key} className={clsx('rounded-lg border px-3 py-2.5', b.accent)}>
                    <p className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                      {t(b.labelKey, { defaultValue: b.labelDefault })}
                    </p>
                    <p
                      className={clsx(
                        'mt-1 text-base font-semibold tabular-nums',
                        count === 0
                          ? 'text-content-quaternary'
                          : b.emphasized
                            ? 'text-amber-700 dark:text-amber-300'
                            : 'text-content-primary',
                      )}
                    >
                      {formatCurrency(cost, row.currency, undefined, { maximumFractionDigits: 0 })}
                    </p>
                    <p className="mt-0.5 flex items-center gap-1.5 text-2xs text-content-tertiary tabular-nums">
                      {days !== 0 && (
                        <span className="inline-flex items-center gap-0.5">
                          <CalendarClock size={11} />
                          {signed(days)} {t('moc.days', { defaultValue: 'days' })}
                        </span>
                      )}
                      <span
                        className="text-content-quaternary"
                        title={t('moc.exposure_count_title', { defaultValue: 'Number of changes' })}
                      >
                        ({count})
                      </span>
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {declinedCount > 0 && (
        <div className="px-4 py-2 border-t border-border-light bg-surface-secondary/20 text-2xs text-content-tertiary">
          {t('moc.exposure_declined_note', {
            defaultValue: 'Declined changes are excluded from exposure ({{count}})',
            count: declinedCount,
          })}
        </div>
      )}
    </Card>
  );
}

/* -- Create / Edit modal --------------------------------------------------- */

interface MoCFormData {
  title: string;
  description: string;
  change_category: MoCChangeCategory;
  risk_level: MoCRiskLevel;
  cost_impact: string;
  currency: string;
  schedule_delta_days: string;
}

const EMPTY_FORM: MoCFormData = {
  title: '',
  description: '',
  change_category: 'engineering',
  risk_level: 'medium',
  cost_impact: '',
  currency: '',
  schedule_delta_days: '',
};

/**
 * The form state a change request opens with.
 *
 * Pure and exported so the submit handler can rebuild the same baseline the
 * modal started from and send only what the user actually changed. Prefilling
 * from a row and then PATCHing every field back rewrites fields nobody opened
 * with the values they held when the list was last read, quietly undoing an
 * edit somebody else made in between.
 *
 * Category and risk are narrowed against the known sets here rather than
 * trusted from the row, so a value this page cannot render falls back to the
 * same option the select shows. Doing that in one place is what keeps the
 * baseline identical to the seed.
 */
export function mocFormData(entry?: MoCEntry): MoCFormData {
  if (!entry) return EMPTY_FORM;
  return {
    title: entry.title,
    description: entry.description,
    change_category: (CATEGORIES.includes(entry.change_category as MoCChangeCategory)
      ? entry.change_category
      : 'other') as MoCChangeCategory,
    risk_level: (RISK_LEVELS.includes(entry.risk_level as MoCRiskLevel)
      ? entry.risk_level
      : 'medium') as MoCRiskLevel,
    cost_impact: entry.cost_impact && entry.cost_impact !== '0' ? entry.cost_impact : '',
    currency: entry.currency,
    schedule_delta_days: entry.schedule_delta_days ? String(entry.schedule_delta_days) : '',
  };
}

function MoCFormModal({
  mode,
  initial,
  onClose,
  onSubmit,
  isPending,
  projectName,
}: {
  mode: 'create' | 'edit';
  initial?: MoCFormData;
  onClose: () => void;
  onSubmit: (data: MoCFormData) => void;
  isPending: boolean;
  projectName?: string;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<MoCFormData>(initial ?? EMPTY_FORM);
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof MoCFormData>(key: K, value: MoCFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const titleError = touched && form.title.trim().length === 0;
  const canSubmit = form.title.trim().length > 0;

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
        aria-label={t('moc.new_change', { defaultValue: 'New change request' })}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div>
            <h2 className="text-lg font-semibold text-content-primary">
              {mode === 'create'
                ? t('moc.new_change', { defaultValue: 'New change request' })
                : t('moc.edit_change', { defaultValue: 'Edit change request' })}
            </h2>
            {projectName && (
              <p className="text-xs text-content-tertiary mt-0.5">
                {t('common.creating_in_project', { defaultValue: 'In {{project}}', project: projectName })}
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
          {/* Category */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-2">
              {t('moc.field_category', { defaultValue: 'Change category' })}
            </label>
            <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
              {CATEGORIES.map((cat) => {
                const cfg = CATEGORY_CONFIG[cat];
                const Icon = cfg.icon;
                const selected = form.change_category === cat;
                return (
                  <button
                    key={cat}
                    type="button"
                    onClick={() => set('change_category', cat)}
                    className={clsx(
                      'flex flex-col items-center gap-1.5 rounded-lg border-2 px-2 py-2.5 text-center transition-all',
                      selected
                        ? cfg.color + ' ring-2 ring-oe-blue/30'
                        : 'border-border bg-surface-primary text-content-tertiary hover:border-border-light hover:bg-surface-secondary',
                    )}
                  >
                    <Icon size={18} />
                    <span className="text-2xs font-medium leading-tight">
                      {t(`moc.category_${cat}`, { defaultValue: MOC_CATEGORY_LABELS[cat] ?? cap(cat) })}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Risk level */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-2">
              {t('moc.field_risk', { defaultValue: 'Risk level' })}
            </label>
            <div className="grid grid-cols-4 gap-2">
              {RISK_LEVELS.map((risk) => {
                const selected = form.risk_level === risk;
                const cfg = RISK_CONFIG[risk];
                return (
                  <button
                    key={risk}
                    type="button"
                    onClick={() => set('risk_level', risk)}
                    className={clsx(
                      'flex items-center justify-center gap-1.5 rounded-lg border-2 px-3 py-2.5 transition-all',
                      selected
                        ? cfg.cls + ' border-current ring-2 ring-oe-blue/20'
                        : 'border-border bg-surface-primary text-content-tertiary hover:border-border-light hover:bg-surface-secondary',
                    )}
                  >
                    <span className="text-xs font-semibold">
                      {t(`moc.risk_${risk}`, { defaultValue: cap(risk) })}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Title */}
          <div>
            <label htmlFor="moc-title" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('moc.field_title', { defaultValue: 'Title' })} <span className="text-semantic-error">*</span>
            </label>
            <input
              id="moc-title"
              value={form.title}
              onChange={(e) => {
                set('title', e.target.value);
                setTouched(true);
              }}
              placeholder={t('moc.title_placeholder', {
                defaultValue: 'e.g. Switch facade cladding from brick to rainscreen panels',
              })}
              className={clsx(inputCls, titleError && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error')}
              autoFocus
            />
            {titleError && (
              <p className="mt-1 text-xs text-semantic-error">
                {t('moc.title_required', { defaultValue: 'Title is required' })}
              </p>
            )}
          </div>

          {/* Description */}
          <div>
            <label htmlFor="moc-description" className="block text-sm font-medium text-content-primary mb-1.5">
              {t('moc.field_description', { defaultValue: 'Description' })}
            </label>
            <textarea
              id="moc-description"
              value={form.description}
              onChange={(e) => set('description', e.target.value)}
              rows={4}
              className={textareaCls}
              placeholder={t('moc.description_placeholder', {
                defaultValue: 'What is changing, why, and what triggered it...',
              })}
            />
          </div>

          {/* Impact figures */}
          <div className="flex items-center gap-2 pt-1 pb-1">
            <DollarSign size={14} className="text-content-tertiary" />
            <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('moc.section_impact', { defaultValue: 'Headline impact' })}
            </span>
            <div className="flex-1 h-px bg-border-light" />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label htmlFor="moc-cost" className="block text-xs font-medium text-content-secondary mb-1.5">
                {t('moc.field_cost_impact', { defaultValue: 'Cost impact' })}
              </label>
              <input
                id="moc-cost"
                value={form.cost_impact}
                onChange={(e) => set('cost_impact', e.target.value)}
                inputMode="decimal"
                placeholder="0.00"
                className={inputCls + ' tabular-nums'}
              />
            </div>
            <div>
              <label htmlFor="moc-currency" className="block text-xs font-medium text-content-secondary mb-1.5">
                {t('moc.field_currency', { defaultValue: 'Currency' })}
              </label>
              <input
                id="moc-currency"
                value={form.currency}
                onChange={(e) => set('currency', e.target.value.toUpperCase().slice(0, 6))}
                placeholder={t('moc.currency_placeholder', { defaultValue: 'Project default' })}
                className={inputCls + ' uppercase'}
              />
            </div>
            <div>
              <label htmlFor="moc-days" className="block text-xs font-medium text-content-secondary mb-1.5">
                {t('moc.field_schedule_delta', { defaultValue: 'Schedule delta (days)' })}
              </label>
              <input
                id="moc-days"
                value={form.schedule_delta_days}
                onChange={(e) => set('schedule_delta_days', e.target.value.replace(/[^0-9-]/g, ''))}
                inputMode="numeric"
                placeholder="0"
                className={inputCls + ' tabular-nums'}
              />
            </div>
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
              {mode === 'create'
                ? t('moc.create_change', { defaultValue: 'Create change request' })
                : t('common.save', { defaultValue: 'Save' })}
            </span>
          </Button>
        </div>
      </div>
    </div>
  );
}

/* -- Transition modal (captures notes) ------------------------------------- */

function TransitionModal({
  action,
  entry,
  onClose,
  onConfirm,
  isPending,
}: {
  action: MoCTransition;
  entry: MoCEntry;
  onClose: () => void;
  onConfirm: (notes: string) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [notes, setNotes] = useState('');
  const cfg = TRANSITION_CONFIG[action];
  const Icon = cfg.icon;

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const titleMap: Record<MoCTransition, string> = {
    review: t('moc.confirm_review_title', { defaultValue: 'Mark as reviewed' }),
    accept: t('moc.confirm_accept_title', { defaultValue: 'Approve this change' }),
    decline: t('moc.confirm_decline_title', { defaultValue: 'Decline this change' }),
    implement: t('moc.confirm_implement_title', { defaultValue: 'Mark as implemented' }),
  };
  const bodyMap: Record<MoCTransition, string> = {
    review: t('moc.confirm_review_body', {
      defaultValue: 'Confirms the change request has been technically reviewed and is ready for an approval decision.',
    }),
    accept: t('moc.confirm_accept_body', {
      defaultValue: 'Approves the change. The cost and schedule impact are accepted and the change can be implemented.',
    }),
    decline: t('moc.confirm_decline_body', {
      defaultValue: 'Rejects the change request. This is final and the request cannot be re-opened.',
    }),
    implement: t('moc.confirm_implement_body', {
      defaultValue: 'Records that the approved change has been carried out on site / in the model.',
    }),
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in">
      <div
        className="w-full max-w-md bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4"
        role="dialog"
        aria-modal="true"
        aria-label={titleMap[action]}
      >
        <div className="px-6 py-4 border-b border-border-light flex items-center gap-3">
          <span
            className={clsx(
              'flex h-9 w-9 items-center justify-center rounded-lg shrink-0',
              action === 'decline'
                ? 'bg-red-50 text-red-600 dark:bg-red-950/30 dark:text-red-400'
                : 'bg-blue-50 text-blue-600 dark:bg-blue-950/30 dark:text-blue-400',
            )}
          >
            <Icon size={18} />
          </span>
          <div>
            <h2 className="text-base font-semibold text-content-primary">{titleMap[action]}</h2>
            <p className="text-xs text-content-tertiary font-mono">{entry.code}</p>
          </div>
        </div>
        <div className="px-6 py-4 space-y-3">
          <p className="text-sm text-content-secondary">{bodyMap[action]}</p>
          <div>
            <label htmlFor="moc-trans-notes" className="block text-xs font-medium text-content-secondary mb-1.5">
              {t(`moc.notes_${action}`, { defaultValue: cfg.notesLabel })}
              <span className="text-content-quaternary font-normal">
                {' '}
                ({t('common.optional', { defaultValue: 'optional' })})
              </span>
            </label>
            <textarea
              id="moc-trans-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              autoFocus
              className={textareaCls}
              placeholder={t('moc.notes_placeholder', { defaultValue: 'Add a short note for the audit trail...' })}
            />
          </div>
        </div>
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant={cfg.variant} onClick={() => onConfirm(notes)} disabled={isPending}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <Icon size={15} className="mr-1.5 shrink-0" />
            )}
            <span>{t(`moc.action_${action}`, { defaultValue: MOC_ACTION_LABELS[action] ?? cap(action) })}</span>
          </Button>
        </div>
      </div>
    </div>
  );
}

/* -- Add impact modal ------------------------------------------------------ */

const IMPACT_AREAS = ['cost', 'schedule', 'safety', 'quality', 'environment', 'design', 'other'];
const IMPACT_SEVERITIES = ['low', 'medium', 'high', 'critical'];

function AddImpactModal({
  entry,
  onClose,
  onSubmit,
  isPending,
}: {
  entry: MoCEntry;
  onClose: () => void;
  onSubmit: (data: CreateImpactPayload) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [area, setArea] = useState('cost');
  const [severity, setSeverity] = useState('medium');
  const [description, setDescription] = useState('');
  const [mitigation, setMitigation] = useState('');
  const [cost, setCost] = useState('');
  const [days, setDays] = useState('');

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
        className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto"
        role="dialog"
        aria-modal="true"
        aria-label={t('moc.add_impact', { defaultValue: 'Add impact assessment' })}
      >
        <div className="px-6 py-4 border-b border-border-light flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-content-primary">
              {t('moc.add_impact', { defaultValue: 'Add impact assessment' })}
            </h2>
            <p className="text-xs text-content-tertiary font-mono">{entry.code}</p>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>
        <div className="px-6 py-4 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="imp-area" className="block text-xs font-medium text-content-secondary mb-1.5">
                {t('moc.impact_area', { defaultValue: 'Impact area' })}
              </label>
              <select
                id="imp-area"
                value={area}
                onChange={(e) => setArea(e.target.value)}
                className={inputCls + ' capitalize'}
              >
                {IMPACT_AREAS.map((a) => (
                  <option key={a} value={a}>
                    {t(`moc.area_${a}`, { defaultValue: cap(a) })}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="imp-sev" className="block text-xs font-medium text-content-secondary mb-1.5">
                {t('moc.impact_severity', { defaultValue: 'Severity' })}
              </label>
              <select
                id="imp-sev"
                value={severity}
                onChange={(e) => setSeverity(e.target.value)}
                className={inputCls + ' capitalize'}
              >
                {IMPACT_SEVERITIES.map((s) => (
                  <option key={s} value={s}>
                    {t(`moc.risk_${s}`, { defaultValue: cap(s) })}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <label htmlFor="imp-desc" className="block text-xs font-medium text-content-secondary mb-1.5">
              {t('moc.field_description', { defaultValue: 'Description' })}
            </label>
            <textarea
              id="imp-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className={textareaCls}
              placeholder={t('moc.impact_desc_placeholder', { defaultValue: 'What is affected and how...' })}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="imp-cost" className="block text-xs font-medium text-content-secondary mb-1.5">
                {t('moc.field_cost_impact', { defaultValue: 'Cost impact' })}
              </label>
              <input
                id="imp-cost"
                value={cost}
                onChange={(e) => setCost(e.target.value)}
                inputMode="decimal"
                placeholder="0.00"
                className={inputCls + ' tabular-nums'}
              />
            </div>
            <div>
              <label htmlFor="imp-days" className="block text-xs font-medium text-content-secondary mb-1.5">
                {t('moc.field_schedule_delta', { defaultValue: 'Schedule delta (days)' })}
              </label>
              <input
                id="imp-days"
                value={days}
                onChange={(e) => setDays(e.target.value.replace(/[^0-9-]/g, ''))}
                inputMode="numeric"
                placeholder="0"
                className={inputCls + ' tabular-nums'}
              />
            </div>
          </div>
          <div>
            <label htmlFor="imp-mit" className="block text-xs font-medium text-content-secondary mb-1.5">
              {t('moc.impact_mitigation', { defaultValue: 'Mitigation' })}
            </label>
            <textarea
              id="imp-mit"
              value={mitigation}
              onChange={(e) => setMitigation(e.target.value)}
              rows={2}
              className={textareaCls}
              placeholder={t('moc.impact_mit_placeholder', { defaultValue: 'How the impact will be contained or offset...' })}
            />
          </div>
        </div>
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={() =>
              onSubmit({
                impact_area: area,
                severity,
                description,
                mitigation,
                cost_impact: toDecimalPayloadString(cost),
                schedule_delta_days: days ? Number.parseInt(days, 10) : 0,
              })
            }
            disabled={isPending}
          >
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <ListPlus size={15} className="mr-1.5 shrink-0" />
            )}
            <span>{t('moc.add_impact', { defaultValue: 'Add impact' })}</span>
          </Button>
        </div>
      </div>
    </div>
  );
}

/* -- MoC row (expandable) -------------------------------------------------- */

const MoCRow = React.memo(function MoCRow({
  entry,
  onTransition,
  onEdit,
  onDelete,
  onAddImpact,
  onDeleteImpact,
}: {
  entry: MoCEntry;
  onTransition: (entry: MoCEntry, action: MoCTransition) => void;
  onEdit: (entry: MoCEntry) => void;
  onDelete: (entry: MoCEntry) => void;
  onAddImpact: (entry: MoCEntry) => void;
  onDeleteImpact: (entry: MoCEntry, impactId: string) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [expanded, setExpanded] = useState(false);

  const statusCfg = STATUS_CONFIG[entry.status] ?? STATUS_CONFIG.proposed;
  const catKey = (CATEGORIES.includes(entry.change_category as MoCChangeCategory)
    ? entry.change_category
    : 'other') as MoCChangeCategory;
  const catCfg = CATEGORY_CONFIG[catKey];
  const CatIcon = catCfg.icon;
  const riskCfg = RISK_CONFIG[(entry.risk_level as MoCRiskLevel) in RISK_CONFIG ? (entry.risk_level as MoCRiskLevel) : 'medium'];
  const money = formatMoney(entry.cost_impact, entry.currency);
  const terminal = entry.status === 'declined' || entry.status === 'implemented';
  const transitions = NEXT_TRANSITIONS[entry.status] ?? [];

  return (
    <div className="border-b border-border-light last:border-b-0">
      {/* Main row */}
      <div
        className={clsx(
          'flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-surface-secondary/50 transition-colors',
          expanded && 'bg-surface-secondary/30',
        )}
        onClick={() => setExpanded((p) => !p)}
      >
        <ChevronRight size={14} className={clsx('text-content-tertiary transition-transform shrink-0', expanded && 'rotate-90')} />

        <span className="text-sm font-mono font-semibold text-content-secondary w-20 shrink-0">{entry.code}</span>

        <span className="flex items-center gap-1.5 shrink-0" title={t(`moc.category_${catKey}`, { defaultValue: MOC_CATEGORY_LABELS[catKey] ?? cap(catKey) })}>
          <CatIcon size={15} className="text-content-tertiary" />
        </span>

        <span className="text-sm text-content-primary truncate flex-1 min-w-0">{entry.title}</span>

        {/* Risk */}
        <Badge variant={riskCfg.variant} size="sm" className={riskCfg.cls}>
          {t(`moc.risk_${entry.risk_level}`, { defaultValue: cap(entry.risk_level) })}
        </Badge>

        {/* Cost impact */}
        <span className="text-xs text-content-tertiary w-28 text-right shrink-0 hidden md:block tabular-nums">
          {money ? (
            <span className="flex items-center justify-end gap-0.5 text-amber-500 font-medium">
              <DollarSign size={12} />
              {money}
            </span>
          ) : (
            '—'
          )}
        </span>

        {/* Status */}
        <Badge variant={statusCfg.variant} size="sm" className={statusCfg.cls}>
          {t(`moc.status_${entry.status}`, { defaultValue: MOC_STATUS_LABELS[entry.status] ?? cap(entry.status) })}
        </Badge>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="px-4 pb-4 pl-12 space-y-3 animate-fade-in">
          {/* Description */}
          {entry.description && (
            <div className="rounded-lg bg-surface-secondary p-3">
              <p className="text-xs text-content-tertiary mb-1 font-medium uppercase tracking-wide">
                {t('moc.label_description', { defaultValue: 'Description' })}
              </p>
              <p className="text-sm text-content-primary whitespace-pre-wrap">{entry.description}</p>
            </div>
          )}

          {/* Headline figures */}
          <div className="flex flex-wrap items-center gap-4 text-xs text-content-tertiary">
            <span className="flex items-center gap-1.5">
              <span
                className={clsx('inline-flex items-center rounded-md border px-1.5 py-0.5 font-medium', catCfg.color)}
              >
                <CatIcon size={11} className="mr-1" />
                {t(`moc.category_${catKey}`, { defaultValue: MOC_CATEGORY_LABELS[catKey] ?? cap(catKey) })}
              </span>
            </span>
            {money && (
              <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400 font-medium">
                <DollarSign size={13} /> {money}
              </span>
            )}
            {entry.schedule_delta_days !== 0 && (
              <span className="flex items-center gap-1">
                <CalendarClock size={13} />
                {entry.schedule_delta_days > 0 ? '+' : ''}
                {entry.schedule_delta_days} {t('moc.days', { defaultValue: 'days' })}
              </span>
            )}
          </div>

          {/* Impact assessment lines */}
          <div className="rounded-lg border border-border-light overflow-hidden">
            <div className="flex items-center justify-between px-3 py-2 bg-surface-secondary/40">
              <span className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary flex items-center gap-1.5">
                <ShieldCheck size={12} />
                {t('moc.impacts_title', { defaultValue: 'Impact assessment' })}
                {entry.impacts.length > 0 && (
                  <span className="text-content-quaternary">({entry.impacts.length})</span>
                )}
              </span>
              {!terminal && (
                <button
                  className="text-2xs text-oe-blue hover:underline flex items-center gap-1"
                  onClick={(e) => {
                    e.stopPropagation();
                    onAddImpact(entry);
                  }}
                >
                  <Plus size={11} />
                  {t('moc.add_impact', { defaultValue: 'Add impact' })}
                </button>
              )}
            </div>
            {entry.impacts.length === 0 ? (
              <p className="px-3 py-2.5 text-xs text-content-quaternary">
                {t('moc.no_impacts', { defaultValue: 'No impact lines recorded yet.' })}
              </p>
            ) : (
              <div className="divide-y divide-border-light">
                {entry.impacts.map((imp) => {
                  const impMoney = formatMoney(imp.cost_impact, imp.currency);
                  const sevCfg = RISK_CONFIG[(imp.severity as MoCRiskLevel) in RISK_CONFIG ? (imp.severity as MoCRiskLevel) : 'medium'];
                  return (
                    <div key={imp.id} className="px-3 py-2 flex items-start gap-3 group">
                      <Badge variant="neutral" size="sm" className="capitalize shrink-0">
                        {t(`moc.area_${imp.impact_area}`, { defaultValue: cap(imp.impact_area) })}
                      </Badge>
                      <Badge variant={sevCfg.variant} size="sm" className={sevCfg.cls + ' shrink-0'}>
                        {t(`moc.risk_${imp.severity}`, { defaultValue: cap(imp.severity) })}
                      </Badge>
                      <div className="flex-1 min-w-0">
                        {imp.description && <p className="text-xs text-content-primary">{imp.description}</p>}
                        {imp.mitigation && (
                          <p className="text-2xs text-content-tertiary mt-0.5">
                            <span className="font-medium">{t('moc.impact_mitigation', { defaultValue: 'Mitigation' })}:</span>{' '}
                            {imp.mitigation}
                          </p>
                        )}
                      </div>
                      <div className="text-right shrink-0 text-2xs tabular-nums text-content-tertiary">
                        {impMoney && <div className="text-amber-600 dark:text-amber-400 font-medium">{impMoney}</div>}
                        {imp.schedule_delta_days !== 0 && (
                          <div>
                            {imp.schedule_delta_days > 0 ? '+' : ''}
                            {imp.schedule_delta_days}d
                          </div>
                        )}
                      </div>
                      {!terminal && (
                        <button
                          className="text-content-quaternary hover:text-semantic-error opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                          aria-label={t('common.delete', { defaultValue: 'Delete' })}
                          onClick={(e) => {
                            e.stopPropagation();
                            onDeleteImpact(entry, imp.id);
                          }}
                        >
                          <Trash2 size={13} />
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Review / decision notes */}
          {entry.review_notes && (
            <div className="rounded-lg bg-blue-50 dark:bg-blue-950/20 border border-blue-200 dark:border-blue-800 p-3">
              <p className="text-xs text-blue-700 dark:text-blue-400 mb-1 font-medium uppercase tracking-wide">
                {t('moc.label_review_notes', { defaultValue: 'Review notes' })}
              </p>
              <p className="text-sm text-content-primary whitespace-pre-wrap">{entry.review_notes}</p>
            </div>
          )}
          {entry.decision_notes && (
            <div
              className={clsx(
                'rounded-lg border p-3',
                entry.status === 'declined'
                  ? 'bg-red-50 dark:bg-red-950/20 border-red-200 dark:border-red-800'
                  : 'bg-green-50 dark:bg-green-950/20 border-green-200 dark:border-green-800',
              )}
            >
              <p
                className={clsx(
                  'text-xs mb-1 font-medium uppercase tracking-wide',
                  entry.status === 'declined' ? 'text-red-700 dark:text-red-400' : 'text-green-700 dark:text-green-400',
                )}
              >
                {t('moc.label_decision_notes', { defaultValue: 'Decision notes' })}
              </p>
              <p className="text-sm text-content-primary whitespace-pre-wrap">{entry.decision_notes}</p>
            </div>
          )}

          {/* Linked commercial records. Each pill lands on the record itself
              (Issue #435): the bare register was the destination before, which
              left the reader to find by hand the record this entry already
              names. The variation pill prefers the order, the contractual
              record, and falls back to the request while no order exists. */}
          {(() => {
            const variationLink = linkedVariationDeepLink(entry);
            const changeOrderId = entry.change_order_id;
            if (!variationLink && !changeOrderId) return null;
            return (
              <div className="flex flex-wrap items-center gap-2">
                {variationLink && (
                  <button
                    className="flex items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 dark:bg-blue-950/20 dark:border-blue-800 px-2.5 py-1.5 text-xs text-blue-700 dark:text-blue-300 hover:bg-blue-100 transition-colors"
                    onClick={(e) => {
                      e.stopPropagation();
                      navigate(variationLink);
                    }}
                  >
                    <Link2 size={12} />
                    {t('moc.linked_variation', { defaultValue: 'Linked variation' })}
                  </button>
                )}
                {changeOrderId && (
                  <button
                    className="flex items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 dark:bg-blue-950/20 dark:border-blue-800 px-2.5 py-1.5 text-xs text-blue-700 dark:text-blue-300 hover:bg-blue-100 transition-colors"
                    onClick={(e) => {
                      e.stopPropagation();
                      navigate(changeOrderDeepLink(changeOrderId));
                    }}
                  >
                    <Link2 size={12} />
                    {t('moc.linked_change_order', { defaultValue: 'Linked change order' })}
                  </button>
                )}
              </div>
            );
          })()}

          {/* Claims evidence: how provable this change is from the record, and
              the reconciled evidence thread around it (deferred behind a button).
              Both self-fetch and degrade to their own empty states. */}
          <div className="grid gap-3 lg:grid-cols-2" onClick={(e) => e.stopPropagation()}>
            <ProvabilityGauge projectId={entry.project_id} subjectKind="moc_entry" subjectId={entry.id} />
            <EvidenceThreadPanel projectId={entry.project_id} subjectType="moc" subjectId={entry.id} />
          </div>

          {/* Audit trail dates */}
          <div className="flex items-center gap-4 text-2xs text-content-quaternary flex-wrap pt-1">
            {entry.proposed_at && (
              <span>
                {t('moc.label_proposed', { defaultValue: 'Proposed' })}: <DateDisplay value={entry.proposed_at} />
              </span>
            )}
            {entry.reviewed_at && (
              <span>
                {t('moc.label_reviewed', { defaultValue: 'Reviewed' })}: <DateDisplay value={entry.reviewed_at} />
              </span>
            )}
            {entry.decided_at && (
              <span>
                {t('moc.label_decided', { defaultValue: 'Decided' })}: <DateDisplay value={entry.decided_at} />
              </span>
            )}
            {entry.implemented_at && (
              <span>
                {t('moc.label_implemented', { defaultValue: 'Implemented' })}: <DateDisplay value={entry.implemented_at} />
              </span>
            )}
          </div>

          {/* FSM actions */}
          <div className="flex items-center gap-2 pt-2 flex-wrap">
            {transitions.map((action) => {
              const cfg = TRANSITION_CONFIG[action];
              const Icon = cfg.icon;
              return (
                <Button
                  key={action}
                  variant={cfg.variant}
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    onTransition(entry, action);
                  }}
                >
                  <Icon size={14} className="mr-1.5" />
                  {t(`moc.action_${action}`, { defaultValue: MOC_ACTION_LABELS[action] ?? cap(action) })}
                </Button>
              );
            })}
            {entry.status === 'proposed' && (
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    onEdit(entry);
                  }}
                >
                  <Pencil size={14} className="mr-1.5" />
                  {t('common.edit', { defaultValue: 'Edit' })}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-semantic-error"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(entry);
                  }}
                >
                  <Trash2 size={14} className="mr-1.5" />
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

/* -- Main page ------------------------------------------------------------- */

export function MoCPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const [showFormModal, setShowFormModal] = useState(false);
  const [editTarget, setEditTarget] = useState<MoCEntry | null>(null);
  const [transitionTarget, setTransitionTarget] = useState<{ entry: MoCEntry; action: MoCTransition } | null>(null);
  const [impactTarget, setImpactTarget] = useState<MoCEntry | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<MoCStatus | ''>('');
  const [categoryFilter, setCategoryFilter] = useState<MoCChangeCategory | ''>('');
  const [riskFilter, setRiskFilter] = useState<MoCRiskLevel | ''>('');
  const [sortMode, setSortMode] = useState<MoCSortMode>('default');

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

  const {
    data: entries = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['moc', projectId, statusFilter],
    queryFn: () => fetchMoCEntries(projectId, statusFilter || undefined),
    enabled: !!projectId,
  });

  // Module Insights - the toggleable KPI/chart panel for this module. Its
  // charts are built client-side from the change requests already loaded; when
  // the project has none the panel draws nothing rather than inventing rows to
  // fill it. The page has no early return, so this simply joins the other
  // top-level hooks. Currency comes from the first entry that carries one (the
  // MoC project record does not expose it).
  const insights = useModuleInsights('moc', { defaultOpen: true });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildMocInsights(entries, entries.find((e) => e.currency)?.currency || '', t),
    [entries, t],
  );

  // Client-side narrowing: category + risk + free-text search, layered on top
  // of the server-side status filter that already scoped `entries`.
  const filtered = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return entries.filter((e) => {
      if (categoryFilter && e.change_category !== categoryFilter) return false;
      if (riskFilter && e.risk_level !== riskFilter) return false;
      if (!q) return true;
      return (
        e.title.toLowerCase().includes(q) ||
        e.code.toLowerCase().includes(q) ||
        e.description.toLowerCase().includes(q)
      );
    });
  }, [entries, searchQuery, categoryFilter, riskFilter]);

  // Sort surfaces the biggest changes first. Cost / schedule sort by absolute
  // magnitude so large savings (negative deltas) rise to the top too.
  const sorted = useMemo(() => {
    if (sortMode === 'default') return filtered;
    const arr = [...filtered];
    arr.sort((a, b) => {
      if (sortMode === 'cost') {
        return Math.abs(toNum(b.cost_impact)) - Math.abs(toNum(a.cost_impact));
      }
      if (sortMode === 'schedule') {
        return Math.abs(toNum(b.schedule_delta_days)) - Math.abs(toNum(a.schedule_delta_days));
      }
      return (RISK_RANK[b.risk_level] ?? 0) - (RISK_RANK[a.risk_level] ?? 0);
    });
    return arr;
  }, [filtered, sortMode]);

  // Exposure rollup: sum the Decimal-string cost_impact (via toNum) and the
  // schedule delta per lifecycle bucket, grouped by currency so different
  // currencies are never blended. Declined changes carry no exposure.
  const exposure = useMemo<CurrencyExposure[]>(() => {
    const map = new Map<string, CurrencyExposure>();
    const blank = (currency: string): CurrencyExposure => ({
      currency,
      cost: { pending: 0, accepted: 0, implemented: 0 },
      days: { pending: 0, accepted: 0, implemented: 0 },
      count: { pending: 0, accepted: 0, implemented: 0 },
    });
    for (const e of filtered) {
      let bucket: ExposureBucket | null = null;
      if (e.status === 'proposed' || e.status === 'reviewed') bucket = 'pending';
      else if (e.status === 'accepted') bucket = 'accepted';
      else if (e.status === 'implemented') bucket = 'implemented';
      if (!bucket) continue; // declined excluded
      const cur = (e.currency || '').trim().toUpperCase();
      let row = map.get(cur);
      if (!row) {
        row = blank(cur);
        map.set(cur, row);
      }
      row.cost[bucket] += toNum(e.cost_impact);
      row.days[bucket] += toNum(e.schedule_delta_days);
      row.count[bucket] += 1;
    }
    // Lead with the currency carrying the largest overall cost exposure.
    return [...map.values()].sort((a, b) => {
      const at = a.cost.pending + a.cost.accepted + a.cost.implemented;
      const bt = b.cost.pending + b.cost.accepted + b.cost.implemented;
      return bt - at;
    });
  }, [filtered]);

  // Only worth rendering the band when it actually reports money or days;
  // a wall of zeros helps nobody.
  const exposureHasFigures = useMemo(
    () =>
      exposure.some(
        (r) =>
          r.cost.pending ||
          r.cost.accepted ||
          r.cost.implemented ||
          r.days.pending ||
          r.days.accepted ||
          r.days.implemented,
      ),
    [exposure],
  );

  const declinedCount = useMemo(
    () => filtered.filter((e) => e.status === 'declined').length,
    [filtered],
  );

  const hasActiveFilters = !!(searchQuery || statusFilter || categoryFilter || riskFilter);

  const resetFilters = useCallback(() => {
    setSearchQuery('');
    setStatusFilter('');
    setCategoryFilter('');
    setRiskFilter('');
  }, []);

  const stats = useMemo(() => {
    const total = entries.length;
    const open = entries.filter((e) => e.status === 'proposed' || e.status === 'reviewed').length;
    const accepted = entries.filter((e) => e.status === 'accepted').length;
    const implemented = entries.filter((e) => e.status === 'implemented').length;
    return { total, open, accepted, implemented };
  }, [entries]);

  // Export the visible register (respecting filters + sort) to CSV, with each
  // impact line as its own row. A UTF-8 BOM keeps non-Latin text readable in
  // spreadsheet tools; text cells are quoted only when they carry a comma,
  // quote or newline.
  const handleExportCSV = useCallback(() => {
    if (!sorted.length) return;
    const esc = (v: string | number | null | undefined): string => {
      const s = v == null ? '' : String(v);
      return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const catLabel = (c: string) => t(`moc.category_${c}`, { defaultValue: MOC_CATEGORY_LABELS[c] ?? cap(c) });
    const riskLabel = (r: string) => t(`moc.risk_${r}`, { defaultValue: cap(r) });
    const statusLabel = (s: string) => t(`moc.status_${s}`, { defaultValue: MOC_STATUS_LABELS[s] ?? cap(s) });
    const areaLabel = (a: string) => t(`moc.area_${a}`, { defaultValue: cap(a) });

    const headers = [
      t('moc.col_code', { defaultValue: 'Code' }),
      t('moc.csv_row_type', { defaultValue: 'Row type' }),
      t('moc.csv_title_area', { defaultValue: 'Title / area' }),
      t('moc.field_category', { defaultValue: 'Change category' }),
      t('moc.csv_risk_severity', { defaultValue: 'Risk / severity' }),
      t('moc.col_status', { defaultValue: 'Status' }),
      t('moc.col_cost', { defaultValue: 'Cost impact' }),
      t('moc.field_currency', { defaultValue: 'Currency' }),
      t('moc.csv_schedule_days', { defaultValue: 'Schedule days' }),
      t('moc.field_description', { defaultValue: 'Description' }),
      t('moc.impact_mitigation', { defaultValue: 'Mitigation' }),
      t('moc.label_proposed', { defaultValue: 'Proposed' }),
      t('moc.label_reviewed', { defaultValue: 'Reviewed' }),
      t('moc.label_decided', { defaultValue: 'Decided' }),
      t('moc.label_implemented', { defaultValue: 'Implemented' }),
    ];
    const changeType = t('moc.csv_type_change', { defaultValue: 'Change' });
    const impactType = t('moc.csv_type_impact', { defaultValue: 'Impact' });

    const lines: string[] = [headers.map(esc).join(',')];
    for (const e of sorted) {
      lines.push(
        [
          e.code,
          changeType,
          e.title,
          catLabel(e.change_category),
          riskLabel(e.risk_level),
          statusLabel(e.status),
          toNum(e.cost_impact).toFixed(2),
          e.currency,
          String(toNum(e.schedule_delta_days)),
          e.description,
          '',
          e.proposed_at ?? '',
          e.reviewed_at ?? '',
          e.decided_at ?? '',
          e.implemented_at ?? '',
        ]
          .map(esc)
          .join(','),
      );
      for (const imp of e.impacts) {
        lines.push(
          [
            e.code,
            impactType,
            areaLabel(imp.impact_area),
            '',
            riskLabel(imp.severity),
            '',
            toNum(imp.cost_impact).toFixed(2),
            imp.currency,
            String(toNum(imp.schedule_delta_days)),
            imp.description,
            imp.mitigation,
            '',
            '',
            '',
            '',
          ]
            .map(esc)
            .join(','),
        );
      }
    }

    const csv = '\uFEFF' + lines.join('\r\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `moc-register-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [sorted, t]);

  const invalidate = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['moc'] });
  }, [qc]);

  const onErr = useCallback(
    (e: Error) =>
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message }),
    [addToast, t],
  );

  const createMut = useMutation({
    mutationFn: (data: CreateMoCPayload) => createMoCEntry(data),
    onSuccess: () => {
      invalidate();
      setShowFormModal(false);
      addToast({ type: 'success', title: t('moc.created', { defaultValue: 'Change request created' }) });
    },
    onError: onErr,
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateMoCPayload }) => updateMoCEntry(id, data),
    onSuccess: () => {
      invalidate();
      setEditTarget(null);
      addToast({ type: 'success', title: t('moc.updated', { defaultValue: 'Change request updated' }) });
    },
    onError: onErr,
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteMoCEntry(id),
    onSuccess: () => {
      invalidate();
      addToast({ type: 'success', title: t('moc.deleted', { defaultValue: 'Change request deleted' }) });
    },
    onError: onErr,
  });

  const transitionMut = useMutation({
    mutationFn: ({ id, action, notes }: { id: string; action: MoCTransition; notes: string }) =>
      transitionMoCEntry(id, action, notes),
    onSuccess: () => {
      invalidate();
      setTransitionTarget(null);
      addToast({ type: 'success', title: t('moc.transitioned', { defaultValue: 'Status updated' }) });
    },
    onError: onErr,
  });

  const addImpactMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: CreateImpactPayload }) => addMoCImpact(id, data),
    onSuccess: () => {
      invalidate();
      setImpactTarget(null);
      addToast({ type: 'success', title: t('moc.impact_added', { defaultValue: 'Impact added' }) });
    },
    onError: onErr,
  });

  const deleteImpactMut = useMutation({
    mutationFn: ({ entryId, impactId }: { entryId: string; impactId: string }) =>
      deleteMoCImpact(entryId, impactId),
    onSuccess: () => invalidate(),
    onError: onErr,
  });

  const { confirm, ...confirmProps } = useConfirm();

  const handleFormSubmit = useCallback(
    (form: MoCFormData) => {
      const payload = {
        title: form.title.trim(),
        description: form.description,
        change_category: form.change_category,
        risk_level: form.risk_level,
        cost_impact: toDecimalPayloadString(form.cost_impact),
        currency: form.currency,
        schedule_delta_days: form.schedule_delta_days ? Number.parseInt(form.schedule_delta_days, 10) : 0,
      };
      if (editTarget) {
        // Rebuild the baseline the modal started from, so the save carries only
        // what the user actually edited. See `mocFormData`.
        updateMut.mutate({
          id: editTarget.id,
          data: onlyChangedFields(payload, form, mocFormData(editTarget)),
        });
      } else {
        if (!projectId) {
          addToast({
            type: 'error',
            title: t('common.error', { defaultValue: 'Error' }),
            message: t('common.select_project_first', { defaultValue: 'Please select a project first' }),
          });
          return;
        }
        createMut.mutate({ project_id: projectId, ...payload });
      }
    },
    [editTarget, updateMut, createMut, projectId, addToast, t],
  );

  const handleDelete = useCallback(
    async (entry: MoCEntry) => {
      const ok = await confirm({
        title: t('moc.confirm_delete_title', { defaultValue: 'Delete change request?' }),
        message: t('moc.confirm_delete_msg', {
          defaultValue: '{{code}} will be permanently removed. Only proposed requests can be deleted.',
          code: entry.code,
        }),
        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
        variant: 'danger',
      });
      if (ok) deleteMut.mutate(entry.id);
    },
    [confirm, deleteMut, t],
  );

  const handleDeleteImpact = useCallback(
    async (entry: MoCEntry, impactId: string) => {
      const ok = await confirm({
        title: t('moc.confirm_delete_impact_title', { defaultValue: 'Remove impact line?' }),
        message: t('moc.confirm_delete_impact_msg', { defaultValue: 'This impact assessment line will be removed.' }),
        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
        variant: 'warning',
      });
      if (ok) deleteImpactMut.mutate({ entryId: entry.id, impactId });
    },
    [confirm, deleteImpactMut, t],
  );

  const editInitial: MoCFormData | undefined = editTarget ? mocFormData(editTarget) : undefined;

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(selectedProjectId && breadcrumbProjectName
            ? [{ label: breadcrumbProjectName, to: `/projects/${selectedProjectId}` }]
            : []),
          { label: t('moc.title', { defaultValue: 'Management of Change' }) },
        ]}
      />

      <PageHeader
        srTitle={t('moc.title', { defaultValue: 'Management of Change' })}
        subtitle={t('moc.subtitle', {
          defaultValue: 'Capture, assess, and route deviations from the agreed design, scope, or process',
        })}
        actions={
          <>
            <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
            {/* How it works guide - explains the change-control concepts and
                the raise / assess / review / approve flow. Sits as the
                leading help pill ahead of the primary action. */}
            <ModuleGuideButton
              content={mocGuide}
              onCta={() => {
                setEditTarget(null);
                setShowFormModal(true);
              }}
            />
            <Button
              variant="primary"
              size="sm"
              onClick={() => {
                setEditTarget(null);
                setShowFormModal(true);
              }}
              disabled={!projectId}
              title={!projectId ? t('common.select_project_first', { defaultValue: 'Please select a project first' }) : undefined}
              icon={<Plus size={14} />}
            >
              {t('moc.new_change', { defaultValue: 'New change request' })}
            </Button>
          </>
        }
      />

      <InsightsPanel
        open={insights.open}
        title={t('moc.insights.title', { defaultValue: 'Management of Change insights' })}
        datasets={insightDatasets}
        builtins={insightBuiltins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
      />

      <SectionIntro
        storageKey="moc"
        title={t('moc.intro_title', { defaultValue: 'Control changes before anyone acts' })}
        more={
          <IntroRichText
            text={t('moc.intro_more', {
              defaultValue:
                'Construction projects drift. Someone swaps a material on site, an engineer revises a detail, the client widens the scope, and three weeks later nobody can say who agreed to it, what it cost or what it did to the programme. Management of Change is the gate that stops a deviation from the agreed design, scope or process from happening informally. Every proposed change is captured, assessed and approved before work changes, so there are no surprises at the next valuation.\n\n**You put in:**\n- A change request with a category (engineering, scope, design, process, material, safety, regulatory and more) and a risk level\n- A headline cost impact, currency and schedule delta in days\n- A detailed impact assessment per area (cost, schedule, safety, quality, environment) with severity and mitigation\n- Review and decision notes captured at each step for the audit trail\n\n**You get out:**\n- A controlled register with a unique code per change and a clear status across the pipeline\n- Totals at a glance: total, in progress, accepted and implemented\n- A locked decision history showing who reviewed, who decided and when\n- Links to the commercial records the change generated, so cost and approval never drift apart\n\n**How it works day to day:**\n1. Raise the change request, set its category and risk, and record the headline cost and schedule impact.\n2. Add one or more impact assessment lines so the full effect, not just the headline, is on record.\n3. Move it to reviewed once it has been technically checked and is ready for a decision.\n4. Accept or decline it; a declined request is final and cannot be reopened.\n5. Once the approved change is carried out on site or in the model, mark it implemented.\n\nThe status flow (proposed, reviewed, accepted or declined, implemented) is enforced by the backend, so the page only ever offers the transitions that are legal right now. Approved changes flow on to Variations and Change Orders, which is where the priced commercial instruction lives, keeping the whole change-to-cost trail connected and auditable.',
            })}
          />
        }
        links={[
          { label: t('moc.intro_link_variations', { defaultValue: 'Variations' }), onClick: () => navigate('/variations') },
          { label: t('moc.intro_link_changeorders', { defaultValue: 'Change Orders' }), onClick: () => navigate('/changeorders') },
        ]}
      >
        {t('moc.intro_body', {
          defaultValue:
            'Capture a proposed deviation from the agreed design, scope or process, assess its cost, schedule, safety and quality impact, then route it through review and approval before work changes. Approved changes flow on to Variations and Change Orders so the commercial trail stays connected and every decision is kept for the audit record.',
        })}
      </SectionIntro>

      {projectId ? (
        <>
          {/* Stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
              <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
                {t('moc.stat_total', { defaultValue: 'Total' })}
              </p>
              <p className="text-lg font-semibold mt-1 tabular-nums text-content-primary">{stats.total}</p>
            </div>
            <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
              <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
                {t('moc.stat_open', { defaultValue: 'In progress' })}
              </p>
              <p
                className={clsx(
                  'text-lg font-semibold mt-1 tabular-nums',
                  stats.open > 0 ? 'text-oe-blue' : 'text-content-primary',
                )}
              >
                {stats.open}
              </p>
            </div>
            <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
              <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
                {t('moc.stat_accepted', { defaultValue: 'Accepted' })}
              </p>
              <p className="text-lg font-semibold mt-1 tabular-nums text-emerald-500">{stats.accepted}</p>
            </div>
            <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm animate-card-in">
              <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
                {t('moc.stat_implemented', { defaultValue: 'Implemented' })}
              </p>
              <p className="text-lg font-semibold mt-1 tabular-nums text-semantic-success">{stats.implemented}</p>
            </div>
          </div>

          {/* Toolbar: search, status / category / risk filters, sort, reset,
              and a CSV export of the visible register. */}
          <div className="flex flex-wrap items-center gap-2.5">
            <div className="relative min-w-[180px] flex-1 sm:max-w-xs">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary" />
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t('moc.search_placeholder', { defaultValue: 'Search changes...' })}
                aria-label={t('moc.search_placeholder', { defaultValue: 'Search changes...' })}
                className={inputCls + ' pl-9'}
              />
            </div>
            <div className="relative">
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as MoCStatus | '')}
                aria-label={t('moc.filter_all_statuses', { defaultValue: 'All statuses' })}
                className={selectCls + ' sm:w-44'}
              >
                <option value="">{t('moc.filter_all_statuses', { defaultValue: 'All statuses' })}</option>
                {STATUS_FLOW.map((s) => (
                  <option key={s} value={s}>
                    {t(`moc.status_${s}`, { defaultValue: MOC_STATUS_LABELS[s] ?? cap(s) })}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                <ChevronDown size={14} />
              </div>
            </div>
            <div className="relative">
              <select
                value={categoryFilter}
                onChange={(e) => setCategoryFilter(e.target.value as MoCChangeCategory | '')}
                aria-label={t('moc.filter_all_categories', { defaultValue: 'All categories' })}
                className={selectCls + ' sm:w-44'}
              >
                <option value="">{t('moc.filter_all_categories', { defaultValue: 'All categories' })}</option>
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {t(`moc.category_${c}`, { defaultValue: MOC_CATEGORY_LABELS[c] ?? cap(c) })}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                <ChevronDown size={14} />
              </div>
            </div>
            <div className="relative">
              <select
                value={riskFilter}
                onChange={(e) => setRiskFilter(e.target.value as MoCRiskLevel | '')}
                aria-label={t('moc.filter_all_risks', { defaultValue: 'All risk levels' })}
                className={selectCls + ' sm:w-44'}
              >
                <option value="">{t('moc.filter_all_risks', { defaultValue: 'All risk levels' })}</option>
                {RISK_LEVELS.map((r) => (
                  <option key={r} value={r}>
                    {t(`moc.risk_${r}`, { defaultValue: cap(r) })}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                <ChevronDown size={14} />
              </div>
            </div>
            {/* Register sort. ArrowUpDown is the control affordance. */}
            <div className="relative">
              <select
                value={sortMode}
                onChange={(e) => setSortMode(e.target.value as MoCSortMode)}
                aria-label={t('moc.sort_label', { defaultValue: 'Sort changes' })}
                className={selectCls + ' sm:w-56'}
              >
                {SORT_OPTIONS.map((o) => (
                  <option key={o.mode} value={o.mode}>
                    {t(o.labelKey, { defaultValue: o.labelDefault })}
                  </option>
                ))}
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                <ArrowUpDown size={14} />
              </div>
            </div>
            {hasActiveFilters && (
              <Button
                variant="ghost"
                size="sm"
                onClick={resetFilters}
                icon={<RotateCcw size={14} />}
              >
                {t('moc.reset_filters', { defaultValue: 'Reset filters' })}
              </Button>
            )}
            <Button
              variant="secondary"
              size="sm"
              onClick={handleExportCSV}
              disabled={!sorted.length}
              icon={<Download size={14} />}
            >
              {t('moc.export_csv', { defaultValue: 'Export CSV' })}
            </Button>
          </div>

          {/* Cost and schedule exposure rollup across the visible register. */}
          {exposureHasFigures && (
            <MoCExposureBand rows={exposure} declinedCount={declinedCount} />
          )}

          {/* List */}
          <div>
            {isLoading ? (
              <SkeletonTable rows={5} columns={5} />
            ) : isError ? (
              <RecoveryCard error={error} onRetry={() => refetch()} />
            ) : sorted.length === 0 ? (
              <EmptyState
                icon={<Replace size={28} strokeWidth={1.5} />}
                title={
                  searchQuery || statusFilter
                    ? t('moc.no_results', { defaultValue: 'No matching change requests' })
                    : t('moc.no_entries', { defaultValue: 'No change requests yet' })
                }
                description={
                  searchQuery || statusFilter
                    ? t('moc.no_results_hint', { defaultValue: 'Try adjusting your search or filters' })
                    : t('moc.no_entries_hint', {
                        defaultValue: 'Raise the first change request to start tracking deviations from the agreed plan.',
                      })
                }
                action={
                  !searchQuery && !statusFilter
                    ? {
                        label: t('moc.new_change', { defaultValue: 'New change request' }),
                        onClick: () => {
                          setEditTarget(null);
                          setShowFormModal(true);
                        },
                      }
                    : undefined
                }
              />
            ) : (
              <>
                <p className="mb-3 text-sm text-content-tertiary">
                  {t('moc.showing_count', { defaultValue: '{{count}} change requests', count: sorted.length })}
                </p>
                <Card padding="none" className="overflow-x-auto">
                  <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border-light bg-surface-secondary/30 text-2xs font-medium text-content-tertiary uppercase tracking-wider min-w-[640px]">
                    <span className="w-5" />
                    <span className="w-20">{t('moc.col_code', { defaultValue: 'Code' })}</span>
                    <span className="w-5" />
                    <span className="flex-1">{t('moc.col_title', { defaultValue: 'Title' })}</span>
                    <span className="w-16 text-center">{t('moc.col_risk', { defaultValue: 'Risk' })}</span>
                    <span className="w-28 text-right hidden md:block">{t('moc.col_cost', { defaultValue: 'Cost impact' })}</span>
                    <span className="w-28 text-center">{t('moc.col_status', { defaultValue: 'Status' })}</span>
                  </div>
                  {sorted.map((entry) => (
                    <MoCRow
                      key={entry.id}
                      entry={entry}
                      onTransition={(e, action) => setTransitionTarget({ entry: e, action })}
                      onEdit={(e) => {
                        setEditTarget(e);
                        setShowFormModal(true);
                      }}
                      onDelete={handleDelete}
                      onAddImpact={(e) => setImpactTarget(e)}
                      onDeleteImpact={handleDeleteImpact}
                    />
                  ))}
                </Card>
              </>
            )}
          </div>
        </>
      ) : (
        <RequiresProject
          emptyHint={t('moc.select_project', { defaultValue: 'Open a project first to view and manage change requests.' })}
        >
          {null}
        </RequiresProject>
      )}

      {/* Modals */}
      {showFormModal && (
        <MoCFormModal
          mode={editTarget ? 'edit' : 'create'}
          initial={editInitial}
          onClose={() => {
            setShowFormModal(false);
            setEditTarget(null);
          }}
          onSubmit={handleFormSubmit}
          isPending={createMut.isPending || updateMut.isPending}
          projectName={projectName}
        />
      )}

      {transitionTarget && (
        <TransitionModal
          action={transitionTarget.action}
          entry={transitionTarget.entry}
          onClose={() => setTransitionTarget(null)}
          onConfirm={(notes) =>
            transitionMut.mutate({ id: transitionTarget.entry.id, action: transitionTarget.action, notes })
          }
          isPending={transitionMut.isPending}
        />
      )}

      {impactTarget && (
        <AddImpactModal
          entry={impactTarget}
          onClose={() => setImpactTarget(null)}
          onSubmit={(data) => addImpactMut.mutate({ id: impactTarget.id, data })}
          isPending={addImpactMut.isPending}
        />
      )}

      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

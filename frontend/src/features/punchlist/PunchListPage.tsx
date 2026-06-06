import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  ListChecks,
  Search,
  Plus,
  Filter,
  LayoutList,
  Columns3,
  Calendar,
  Camera,
  Trash2,
  Play,
  CheckCircle2,
  ShieldCheck,
  XCircle,
  AlertTriangle,
  Clock,
  MapPin,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  RecoveryCard,
  ConfirmDialog,
  WideModal,
  WideModalSection,
  WideModalField,
  SkeletonTable,
  IntroRichText,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { SectionIntro } from '@/features/validation';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchPunchItems,
  fetchPunchSummary,
  fetchTeamMembers,
  createPunchItem,
  deletePunchItem,
  transitionPunchStatus,
  bulkClose,
} from './api';
import type {
  PunchItem,
  PunchPriority,
  PunchStatus,
  PunchCategory,
  PunchSummary,
  TeamMember,
  CreatePunchPayload,
} from './api';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
  currency: string;
}

const PRIORITIES: PunchPriority[] = ['low', 'medium', 'high', 'critical'];
const STATUSES: PunchStatus[] = ['open', 'in_progress', 'resolved', 'verified', 'closed'];
const CATEGORIES: PunchCategory[] = [
  'structural',
  'mechanical',
  'electrical',
  'architectural',
  'plumbing',
  'finishing',
  'fire_safety',
  'hvac',
  'exterior',
  'landscaping',
  'general',
];

const KANBAN_COLUMNS: PunchStatus[] = ['open', 'in_progress', 'resolved', 'verified', 'closed'];

const PRIORITY_BADGE_VARIANT: Record<PunchPriority, 'neutral' | 'blue' | 'warning' | 'error'> = {
  low: 'neutral',
  medium: 'warning',
  high: 'error',
  critical: 'error',
};

/** Extra CSS applied to priority badges to differentiate medium (yellow) from high (orange). */
const PRIORITY_BADGE_CLS: Record<PunchPriority, string> = {
  low: '',
  medium: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300',
  high: 'bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300',
  critical: '',
};

/** Left-edge stripe colors for Kanban cards, keyed by priority. */
const PRIORITY_STRIPE_CLS: Record<PunchPriority, string> = {
  low: 'border-l-gray-300 dark:border-l-gray-600',
  medium: 'border-l-yellow-400 dark:border-l-yellow-500',
  high: 'border-l-orange-500 dark:border-l-orange-400',
  critical: 'border-l-red-500 dark:border-l-red-400',
};

const STATUS_BADGE_VARIANT: Record<PunchStatus, 'error' | 'warning' | 'blue' | 'success' | 'neutral'> = {
  open: 'error',
  in_progress: 'warning',
  resolved: 'blue',
  verified: 'success',
  closed: 'neutral',
};

const STATUS_TRANSITION: Record<PunchStatus, { next: PunchStatus; labelKey: string; defaultLabel: string; icon: React.ElementType }[]> = {
  open: [
    { next: 'in_progress', labelKey: 'punch.action_start', defaultLabel: 'Start Work', icon: Play },
  ],
  in_progress: [
    { next: 'resolved', labelKey: 'punch.action_resolve', defaultLabel: 'Mark Resolved', icon: CheckCircle2 },
  ],
  // Reopen targets must mirror the backend FSM (punchlist/service.py
  // VALID_TRANSITIONS): resolved/verified/closed may all go back to "open" —
  // "in_progress" is NOT a legal reopen target and the API rejects it.
  resolved: [
    { next: 'verified', labelKey: 'punch.action_verify', defaultLabel: 'Verify', icon: ShieldCheck },
    { next: 'open', labelKey: 'punch.action_reopen', defaultLabel: 'Reopen', icon: XCircle },
  ],
  verified: [
    { next: 'closed', labelKey: 'punch.action_close', defaultLabel: 'Close', icon: CheckCircle2 },
    { next: 'open', labelKey: 'punch.action_reopen', defaultLabel: 'Reopen', icon: XCircle },
  ],
  closed: [
    { next: 'open', labelKey: 'punch.action_reopen', defaultLabel: 'Reopen', icon: XCircle },
  ],
};

/* ── Styling helpers ──────────────────────────────────────────────────── */

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

type ViewMode = 'list' | 'kanban';

/* ── Source provenance badge ──────────────────────────────────────────── */

/**
 * Resolve the deep-link target for a punch item raised automatically from
 * another module. Reads the source ids the backend stamps into `metadata_`:
 *   - clash: `run_id` (-> the clash run that produced it) / `result_id`
 *   - inspection: `inspection_id` (-> the originating inspection, highlighted)
 *   - ncr: `ncr_id` when present (-> the NCR, highlighted), else the register
 * Returns null for an unknown / source-less item so the caller renders nothing.
 */
function resolvePunchSourceLink(item: PunchItem): { source: string; to: string } | null {
  const md = item.metadata ?? {};
  const source = typeof md.source === 'string' ? md.source : '';
  if (source === 'clash') {
    const runId = typeof md.run_id === 'string' ? md.run_id : '';
    return { source, to: runId ? `/clash?run=${runId}` : '/clash' };
  }
  if (source === 'inspection') {
    const inspectionId = typeof md.inspection_id === 'string' ? md.inspection_id : '';
    return {
      source,
      to: inspectionId
        ? `/projects/${item.project_id}/inspections?highlight=${inspectionId}`
        : '/inspections',
    };
  }
  if (source === 'ncr') {
    // Backend does not yet stamp an ncr id onto punch metadata; fall back to
    // the register and highlight the NCR when an id is available.
    const ncrId =
      typeof md.ncr_id === 'string'
        ? md.ncr_id
        : typeof md.source_ncr_id === 'string'
        ? md.source_ncr_id
        : '';
    return { source, to: ncrId ? `/ncr?highlight=${ncrId}` : '/ncr' };
  }
  return null;
}

function PunchSourceBadge({
  item,
  className,
}: {
  item: PunchItem;
  className?: string;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const link = resolvePunchSourceLink(item);
  if (!link) return null;

  const config: Record<string, { variant: 'error' | 'blue' | 'warning'; label: string }> = {
    clash: { variant: 'error', label: t('punch.source_clash', { defaultValue: 'From clash' }) },
    inspection: {
      variant: 'blue',
      label: t('punch.source_inspection', { defaultValue: 'From Inspection' }),
    },
    ncr: { variant: 'warning', label: t('punch.source_ncr', { defaultValue: 'From NCR' }) },
  };
  const cfg = config[link.source];
  if (!cfg) return null;

  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        navigate(link.to);
      }}
      className={clsx(
        'rounded-md transition-opacity hover:opacity-80 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
        className,
      )}
      title={t('punch.source_open_hint', {
        defaultValue: 'Open the record this item was raised from',
      })}
    >
      <Badge variant={cfg.variant} size="sm">
        {cfg.label}
      </Badge>
    </button>
  );
}

/* ── Stats Cards ──────────────────────────────────────────────────────── */

function StatsCards({ summary }: { summary: PunchSummary | undefined }) {
  const { t } = useTranslation();

  const total = summary?.total ?? 0;
  const byStatus = summary?.by_status ?? {};
  const overdue = summary?.overdue ?? 0;
  const avgDays = summary?.avg_days_to_close;

  const items: { label: string; value: string | number; cls: string }[] = [
    {
      label: t('punch.stat_total', { defaultValue: 'Total' }),
      value: total,
      cls: 'text-content-primary',
    },
    {
      label: t('punch.stat_open', { defaultValue: 'Open' }),
      value: byStatus['open'] ?? 0,
      cls: 'text-semantic-error',
    },
    {
      label: t('punch.stat_in_progress', { defaultValue: 'In Progress' }),
      value: byStatus['in_progress'] ?? 0,
      cls: 'text-amber-700 dark:text-amber-400',
    },
    {
      label: t('punch.stat_resolved', { defaultValue: 'Resolved' }),
      value: byStatus['resolved'] ?? 0,
      cls: 'text-oe-blue',
    },
    {
      label: t('punch.stat_overdue', { defaultValue: 'Overdue' }),
      value: overdue,
      cls: overdue > 0 ? 'text-semantic-error' : 'text-content-primary',
    },
    {
      label: t('punch.stat_avg_close', { defaultValue: 'Avg Days to Close' }),
      value: avgDays != null ? `${avgDays}d` : '-',
      cls: 'text-content-primary',
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {items.map((item) => (
        <div
          key={item.label}
          className="rounded-xl border border-border bg-surface-primary p-3 animate-card-in"
        >
          <p className="text-2xs uppercase tracking-wide text-content-tertiary">{item.label}</p>
          <p className={clsx('mt-1 text-lg font-semibold tabular-nums', item.cls)}>
            {item.value}
          </p>
        </div>
      ))}
    </div>
  );
}

/* ── Add Punch Item Modal ─────────────────────────────────────────────── */

interface PunchFormData {
  title: string;
  description: string;
  priority: PunchPriority;
  category: PunchCategory;
  assigned_to: string;
  due_date: string;
  document_id: string;
  location: string;
}

const EMPTY_FORM: PunchFormData = {
  title: '',
  description: '',
  priority: 'medium',
  category: 'general',
  assigned_to: '',
  due_date: '',
  document_id: '',
  location: '',
};

const PRIORITY_RADIO_COLORS: Record<PunchPriority, string> = {
  low: 'bg-gray-100 text-gray-700 border-gray-300 peer-checked:bg-gray-200 peer-checked:border-gray-500 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600',
  medium: 'bg-blue-50 text-blue-700 border-blue-200 peer-checked:bg-blue-100 peer-checked:border-blue-500 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-700',
  high: 'bg-amber-50 text-amber-700 border-amber-200 peer-checked:bg-amber-100 peer-checked:border-amber-500 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-700',
  critical: 'bg-red-50 text-red-700 border-red-200 peer-checked:bg-red-100 peer-checked:border-red-500 dark:bg-red-900/30 dark:text-red-300 dark:border-red-700',
};

function AddPunchModal({
  onClose,
  onSubmit,
  isPending,
  teamMembers,
}: {
  onClose: () => void;
  onSubmit: (data: PunchFormData) => void;
  isPending: boolean;
  teamMembers: TeamMember[];
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<PunchFormData>(EMPTY_FORM);
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof PunchFormData>(key: K, value: PunchFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const titleError = touched && form.title.trim().length === 0;
  const canSubmit = form.title.trim().length > 0;

  const handleSubmit = () => {
    setTouched(true);
    if (canSubmit) {
      onSubmit(form);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      busy={isPending}
      size="xl"
      title={t('punch.add_item', { defaultValue: 'Add Punch Item' })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <Plus size={16} className="mr-1.5 shrink-0" />
            )}
            <span>{t('punch.create_item', { defaultValue: 'Create Item' })}</span>
          </Button>
        </>
      }
    >
      <WideModalSection columns={2}>
        <WideModalField
          label={t('punch.field_title', { defaultValue: 'Title' })}
          required
          error={titleError ? t('punch.title_required', { defaultValue: 'Title is required' }) : undefined}
          span={2}
          htmlFor="punch-title"
        >
          <input
            id="punch-title"
            value={form.title}
            onChange={(e) => { set('title', e.target.value); setTouched(true); }}
            placeholder={t('punch.title_placeholder', {
              defaultValue: 'e.g. Missing fire seal on Level 3 penetration',
            })}
            className={clsx(inputCls, titleError && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error')}
            autoFocus
          />
        </WideModalField>

        <WideModalField
          label={t('punch.field_description', { defaultValue: 'Description' })}
          span={2}
          htmlFor="punch-description"
        >
          <textarea
            id="punch-description"
            value={form.description}
            onChange={(e) => set('description', e.target.value)}
            rows={2}
            className={textareaCls}
            placeholder={t('punch.description_placeholder', {
              defaultValue: 'Provide details about the issue...',
            })}
          />
        </WideModalField>

        <WideModalField
          label={t('punch.field_priority', { defaultValue: 'Priority' })}
          span={2}
        >
          <div className="flex items-center gap-2 flex-wrap">
            {PRIORITIES.map((p) => (
              <label key={p} className="relative cursor-pointer">
                <input
                  type="radio"
                  name="priority"
                  value={p}
                  checked={form.priority === p}
                  onChange={() => set('priority', p)}
                  className="peer sr-only"
                />
                <div
                  className={clsx(
                    'rounded-lg border px-3 py-1.5 text-center text-sm font-medium transition-all',
                    PRIORITY_RADIO_COLORS[p],
                  )}
                >
                  {t(`punch.priority_${p}`, {
                    defaultValue: p.charAt(0).toUpperCase() + p.slice(1),
                  })}
                </div>
              </label>
            ))}
          </div>
        </WideModalField>

        <WideModalField
          label={t('punch.field_category', { defaultValue: 'Category' })}
          htmlFor="punch-category"
        >
          <select
            id="punch-category"
            value={form.category}
            onChange={(e) => set('category', e.target.value as PunchCategory)}
            className={inputCls}
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {t(`punch.category_${c}`, {
                  defaultValue: c
                    .split('_')
                    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
                    .join(' '),
                })}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField
          label={t('punch.field_assigned_to', { defaultValue: 'Assigned To' })}
          htmlFor="punch-assigned-to"
        >
          <select
            id="punch-assigned-to"
            value={form.assigned_to}
            onChange={(e) => set('assigned_to', e.target.value)}
            className={inputCls}
          >
            <option value="">
              {t('punch.unassigned', { defaultValue: 'Unassigned' })}
            </option>
            {teamMembers.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </WideModalField>

        <WideModalField
          label={t('punch.field_due_date', { defaultValue: 'Due Date' })}
          htmlFor="punch-due-date"
        >
          <input
            id="punch-due-date"
            type="date"
            value={form.due_date}
            onChange={(e) => set('due_date', e.target.value)}
            className={inputCls}
          />
        </WideModalField>

        <WideModalField
          label={t('punch.field_location', { defaultValue: 'Location' })}
          htmlFor="punch-location"
        >
          <input
            id="punch-location"
            value={form.location}
            onChange={(e) => set('location', e.target.value)}
            placeholder={t('punch.location_placeholder', {
              defaultValue: 'e.g. Building A, Level 3, Room 305',
            })}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}

/* ── Kanban Card ──────────────────────────────────────────────────────── */

const PunchKanbanCard = React.memo(function PunchKanbanCard({
  item,
  onTransition,
  onDelete: _onDelete,
}: {
  item: PunchItem;
  onTransition: (id: string, status: PunchStatus) => void;
  onDelete: (id: string) => void;
}) {
  const { t } = useTranslation();
  const transitions = STATUS_TRANSITION[item.status] ?? [];

  const isOverdue =
    item.due_date &&
    item.status !== 'closed' &&
    item.status !== 'verified' &&
    new Date(item.due_date) < new Date();

  return (
    <Card
      className={clsx(
        'p-3 mb-2 hover:shadow-md transition-shadow border-l-4',
        PRIORITY_STRIPE_CLS[item.priority],
        isOverdue && 'bg-red-50/40 dark:bg-red-950/15',
      )}
    >
      {/* Title — bold, clamped to 2 lines */}
      <h4 className={clsx(
        'text-sm font-semibold line-clamp-2',
        isOverdue ? 'text-semantic-error' : 'text-content-primary',
      )}>
        {item.title}
      </h4>

      {/* Description — truncated single line */}
      {item.description && (
        <p className="text-xs text-content-tertiary mt-1 line-clamp-1">
          {item.description}
        </p>
      )}

      {/* Source provenance — a button that deep-links back to the clash,
          inspection or NCR this item was raised from. */}
      {resolvePunchSourceLink(item) && (
        <div className="mt-1">
          <PunchSourceBadge item={item} />
        </div>
      )}

      {/* Bottom row: avatar + due date */}
      <div className="flex items-center justify-between mt-3 text-xs text-content-tertiary">
        {/* Assignee avatar */}
        <div className="flex items-center gap-1.5">
          {item.assigned_to ? (
            <>
              <div className="h-5 w-5 rounded-full bg-oe-blue/10 text-oe-blue flex items-center justify-center text-2xs font-semibold shrink-0">
                {item.assigned_to.charAt(0).toUpperCase()}
              </div>
              <span className="truncate max-w-[80px]">{item.assigned_to}</span>
            </>
          ) : (
            <span className="text-content-quaternary">
              {t('punch.unassigned', { defaultValue: 'Unassigned' })}
            </span>
          )}
        </div>

        {/* Due date + overdue + photos */}
        <div className="flex items-center gap-2">
          {(item.photos || []).length > 0 && (
            <div className="flex items-center gap-0.5">
              <Camera size={11} />
              <span>{(item.photos || []).length}</span>
            </div>
          )}
          {item.due_date && (
            <div
              className={clsx(
                'flex items-center gap-1',
                isOverdue && 'text-semantic-error font-medium',
              )}
            >
              {isOverdue ? <AlertTriangle size={11} /> : <Calendar size={11} />}
              <span>
                {new Date(item.due_date).toLocaleDateString(undefined, {
                  month: 'short',
                  day: 'numeric',
                })}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Transition buttons */}
      {transitions.length > 0 && (
        <div className="flex items-center gap-1 mt-2.5 pt-2 border-t border-border-light">
          {transitions.map((tr) => {
            const Icon = tr.icon;
            return (
              <Button
                key={tr.next}
                variant="ghost"
                size="sm"
                onClick={() => onTransition(item.id, tr.next)}
                className="text-xs shrink-0 whitespace-nowrap"
              >
                <Icon size={12} className="mr-1 shrink-0" />
                <span className="whitespace-nowrap">{t(tr.labelKey, { defaultValue: tr.defaultLabel })}</span>
              </Button>
            );
          })}
        </div>
      )}
    </Card>
  );
});

/* ── Kanban View ──────────────────────────────────────────────────────── */

function KanbanView({
  items,
  onTransition,
  onDelete,
}: {
  items: PunchItem[];
  onTransition: (id: string, status: PunchStatus) => void;
  onDelete: (id: string) => void;
}) {
  const { t } = useTranslation();

  const columns = useMemo(() => {
    const map = new Map<PunchStatus, PunchItem[]>();
    for (const st of KANBAN_COLUMNS) map.set(st, []);
    for (const item of items) {
      const col = map.get(item.status);
      if (col) col.push(item);
    }
    return map;
  }, [items]);

  const COLUMN_HEADER_CLS: Record<PunchStatus, string> = {
    open: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
    in_progress: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400',
    resolved: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
    verified: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
    closed: 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-400',
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4">
      {KANBAN_COLUMNS.map((status) => {
        const colItems = columns.get(status) ?? [];
        return (
          <div key={status} className="flex flex-col">
            {/* Column header */}
            <div
              className={clsx(
                'rounded-lg px-3 py-2 mb-3 flex items-center justify-between',
                COLUMN_HEADER_CLS[status],
              )}
            >
              <span className="text-sm font-semibold">
                {t(`punch.status_${status}`, {
                  defaultValue: status
                    .split('_')
                    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
                    .join(' '),
                })}
              </span>
              <span className="text-xs font-bold rounded-full px-2 py-0.5 bg-white/30">
                {colItems.length}
              </span>
            </div>

            {/* Column items */}
            <div className="flex-1 min-h-[100px]">
              {colItems.length === 0 ? (
                <div className="flex items-center justify-center py-8 text-xs text-content-quaternary">
                  {t('punch.kanban_empty', { defaultValue: 'No items' })}
                </div>
              ) : (
                colItems.map((item) => (
                  <PunchKanbanCard
                    key={item.id}
                    item={item}
                    onTransition={onTransition}
                    onDelete={onDelete}
                  />
                ))
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function PunchListPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const { confirm, ...confirmProps } = useConfirm();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // Deep-link target (e.g. from an inspection's "Open punch item" toast). The
  // matching row scrolls into view and flashes once the data has loaded.
  const highlightId = searchParams.get('highlight');

  // State
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [showAddModal, setShowAddModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterPriority, setFilterPriority] = useState<PunchPriority | ''>('');
  const [filterStatus, setFilterStatus] = useState<PunchStatus | ''>('');
  const [filterCategory, setFilterCategory] = useState<PunchCategory | ''>('');
  const [filterAssignee, setFilterAssignee] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Data queries
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const projectId = activeProjectId || projects[0]?.id || '';
  // Breadcrumb only links a project when one is explicitly in the global
  // context (never the projects[0] fallback), matching the rest of the cluster.
  const breadcrumbProjectName = activeProjectId
    ? projects.find((p) => p.id === activeProjectId)?.name
    : undefined;

  const { data: punchItems = [], isLoading, isError, error, refetch } = useQuery({
    queryKey: ['punchlist', projectId, filterPriority, filterStatus, filterCategory, filterAssignee],
    queryFn: () =>
      fetchPunchItems(projectId, {
        priority: filterPriority || undefined,
        status: filterStatus || undefined,
        category: filterCategory || undefined,
        assigned_to: filterAssignee || undefined,
      }),
    enabled: !!projectId,
  });

  const { data: summary } = useQuery({
    queryKey: ['punchlist-summary', projectId],
    queryFn: () => fetchPunchSummary(projectId),
    enabled: !!projectId,
  });

  const { data: teamMembers = [] } = useQuery({
    queryKey: ['team-members', projectId],
    queryFn: () => fetchTeamMembers(projectId),
    enabled: !!projectId,
  });

  // Client-side search
  const filteredItems = useMemo(() => {
    if (!searchQuery.trim()) return punchItems;
    const q = searchQuery.toLowerCase();
    return punchItems.filter(
      (item) =>
        item.title.toLowerCase().includes(q) ||
        item.description.toLowerCase().includes(q) ||
        (item.assigned_to && item.assigned_to.toLowerCase().includes(q)),
    );
  }, [punchItems, searchQuery]);

  // Clear stale selection whenever the project switches
  useEffect(() => {
    setSelectedIds(new Set());
  }, [projectId]);

  // A deep-link highlight only renders in the list view (the table row carries
  // the flash); switch to it so the targeted item is actually visible.
  useEffect(() => {
    if (highlightId) setViewMode('list');
  }, [highlightId]);

  // Once the highlighted item is present, let the row flash then drop the
  // ?highlight param (replace, preserving other params) so a refresh or
  // back-navigation does not re-trigger the highlight.
  useEffect(() => {
    if (!highlightId) return;
    if (!punchItems.some((it) => it.id === highlightId)) return;
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
  }, [highlightId, punchItems, setSearchParams]);

  // Invalidation
  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['punchlist'] });
    qc.invalidateQueries({ queryKey: ['punchlist-summary'] });
  }, [qc]);

  // Mutations
  const createMut = useMutation({
    mutationFn: (data: CreatePunchPayload) => createPunchItem(data),
    onSuccess: () => {
      invalidateAll();
      setShowAddModal(false);
      addToast({
        type: 'success',
        title: t('punch.item_created', { defaultValue: 'Punch item created' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const transitionMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: PunchStatus }) =>
      transitionPunchStatus(id, status),
    onSuccess: (_data, vars) => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('punch.status_updated', {
          defaultValue: 'Status updated to {{status}}',
          status: t(`punch.status_${vars.status}`, {
            defaultValue: vars.status.replace('_', ' '),
          }),
        }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const delMut = useMutation({
    mutationFn: (id: string) => deletePunchItem(id),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('punch.item_deleted', { defaultValue: 'Punch item deleted' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const bulkCloseMut = useMutation({
    mutationFn: (ids: string[]) => bulkClose(ids, projectId),
    onSuccess: (data) => {
      invalidateAll();
      setSelectedIds(new Set());
      addToast({
        type: data.errors.length > 0 ? 'warning' : 'success',
        title: t('punch.bulk_close_done', {
          defaultValue: 'Closed {{closed}} item(s)',
          closed: data.closed,
        }),
        message:
          data.skipped || data.errors.length
            ? t('punch.bulk_close_detail', {
                defaultValue: '{{skipped}} skipped, {{errors}} error(s)',
                skipped: data.skipped,
                errors: data.errors.length,
              })
            : undefined,
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  // Selection helpers
  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const clearSelection = useCallback(() => setSelectedIds(new Set()), []);

  const handleBulkClose = useCallback(async () => {
    if (selectedIds.size === 0) return;
    const ok = await confirm({
      title: t('punch.confirm_bulk_close_title', {
        defaultValue: 'Close selected items?',
      }),
      message: t('punch.confirm_bulk_close_message', {
        defaultValue:
          'Mark {{count}} punch item(s) as closed? Items already closed will be skipped.',
        count: selectedIds.size,
      }),
      confirmLabel: t('punch.action_close', { defaultValue: 'Close' }),
      variant: 'warning',
    });
    if (ok) bulkCloseMut.mutate(Array.from(selectedIds));
  }, [selectedIds, bulkCloseMut, confirm, t]);

  // Handlers
  const handleCreateSubmit = useCallback(
    (formData: PunchFormData) => {
      createMut.mutate({
        project_id: projectId,
        title: formData.title,
        description: formData.description || undefined,
        priority: formData.priority,
        category: formData.category,
        assigned_to: formData.assigned_to || undefined,
        due_date: formData.due_date || undefined,
        document_id: formData.document_id || undefined,
      });
    },
    [createMut, projectId],
  );

  const handleTransition = useCallback(
    (id: string, status: PunchStatus) => {
      transitionMut.mutate({ id, status });
    },
    [transitionMut],
  );

  const handleDelete = useCallback(
    async (id: string) => {
      const ok = await confirm({
        title: t('punch.confirm_delete_title', {
          defaultValue: 'Delete punch list item?',
        }),
        message: t('punchlist.confirm_delete', {
          defaultValue: 'Delete this punch list item? This cannot be undone.',
        }),
        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
        variant: 'danger',
      });
      if (ok) delMut.mutate(id);
    },
    [delMut, confirm, t],
  );

  return (
    <div className="animate-fade-in space-y-5">
      {/* Breadcrumb — the Home icon already links to the dashboard, and a lone
          module label auto-hides (MODULE_STYLE_GUIDE section 2.1), so no
          literal "Dashboard" item. A project link is added once one is in
          context, matching the rest of the quality cluster. */}
      <Breadcrumb
        items={[
          ...(breadcrumbProjectName && activeProjectId
            ? [{ label: breadcrumbProjectName, to: `/projects/${activeProjectId}` }]
            : []),
          { label: t('punch.title', { defaultValue: 'Punch List' }) },
        ]}
      />

      {/* ── Header: subtitle + primary actions ─────────────────────────── */}
      {/* Module title and icon live in the global top app bar; project
          selection is handled by the global top bar and read here from the
          shared project context. */}
      <PageHeader
        srTitle={t('punch.title', { defaultValue: 'Punch List' })}
        subtitle={t('punch.header_subtitle', {
          defaultValue: 'Track snags and deficiencies through to close-out',
        })}
        actions={
          <>
            {projectId && (
              <Button
                variant="secondary"
                size="sm"
                icon={<MapPin size={14} />}
                onClick={() => navigate(`/projects/${projectId}/geo`)}
                title={t('geo_hub.view_on_map', { defaultValue: 'View on map' })}
                data-testid="punchlist-view-on-map"
              >
                {t('geo_hub.view_on_map', { defaultValue: 'View on map' })}
              </Button>
            )}
            <Button
              variant="primary"
              size="sm"
              onClick={() => setShowAddModal(true)}
              disabled={!projectId}
              icon={<Plus size={14} />}
            >
              {t('punch.new_item', { defaultValue: 'New Item' })}
            </Button>
          </>
        }
      />

      <SectionIntro
        storageKey="punchlist"
        title={t('punch.intro_title', {
          defaultValue: 'Nothing slips through at handover',
        })}
        more={
          <IntroRichText
            text={t('punch.intro_more', {
              defaultValue:
                'Near the end of a job the small stuff piles up: a scuffed door, a missing fire seal, a tile that is not bedded right, a socket that does not work. These are not formal non-conformances, they are snags that just need someone to go and fix them and someone else to confirm they are done. The Punch List is the running register of that outstanding work, so handover is not held up by a hundred half-remembered items on a clipboard.\n\n**You put in:**\n- Punch items with a title, description and a photo or two of the problem\n- A priority (low to critical), a category (structural, MEP, finishing and so on) and a location\n- An assignee and a due date so each item has an owner and a deadline\n- Items raised automatically from a failed inspection, an NCR or a model clash, tagged with their source\n\n**You get out:**\n- A KPI strip showing total, open, in-progress, resolved, overdue and average days to close\n- A Kanban board to manage flow and a list view for bulk triage and close-out\n- A clear status lifecycle for every item, with overdue items flagged in red\n- Bulk close, per-item photos and a map view to see snags by location on site\n\n**How it works day to day:**\n1. Capture the snag during a walkthrough, set its priority and location, and assign it.\n2. The owner moves it Open to In Progress to Resolved as they work it.\n3. A checker verifies the fix and moves it Resolved to Verified to Closed.\n4. If the fix does not hold up on a re-check, reopen it straight back to Open from Resolved, Verified or Closed.\n5. Use the list view to multi-select and bulk close a batch once a zone is signed off.\n\nThe status flow is enforced by the backend, so only legal moves are offered, and reopen always goes back to Open rather than an invalid intermediate state. Items that came from a failed Inspection or an NCR keep a source badge so you can trace them to their origin, which keeps the inspect, defect and close-out loop honest right through to handover.',
            })}
          />
        }
        links={[
          {
            label: t('punch.intro_link_inspections', { defaultValue: 'Inspections' }),
            onClick: () => navigate('/inspections'),
          },
          {
            label: t('punch.intro_link_ncr', { defaultValue: 'NCRs' }),
            onClick: () => navigate('/ncr'),
          },
        ]}
      >
        {t('punch.intro_body', {
          defaultValue:
            'Punch list items capture outstanding work, snags and minor defects. Move each item Open to In Progress to Resolved to Verified to Closed, and reopen anything back to Open straight from Resolved, Verified or Closed when a fix does not hold up on a re-check. Items raised from a failed inspection or an NCR are tagged with their source so you can trace them back. Use the Kanban view to manage flow, the list view for bulk triage.',
        })}
      </SectionIntro>

      {/* KPI strip */}
      <StatsCards summary={summary} />

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
            placeholder={t('punch.search', {
              defaultValue: 'Search title, description, location...',
            })}
            aria-label={t('punch.search', { defaultValue: 'Search title, description, location...' })}
            className={inputCls + ' pl-9'}
          />
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowFilters(!showFilters)}
            className={clsx('shrink-0 whitespace-nowrap', showFilters && 'text-oe-blue')}
          >
            <Filter size={14} className="mr-1.5 shrink-0" />
            <span className="whitespace-nowrap">{t('common.filters', { defaultValue: 'Filters' })}</span>
          </Button>

          {/* View toggle */}
          <div className="flex items-center rounded-lg border border-border overflow-hidden">
            <button
              onClick={() => setViewMode('list')}
              aria-label={t('punch.view_list', { defaultValue: 'List view' })}
              className={clsx(
                'flex items-center gap-1 px-3 py-2 text-sm transition-colors',
                viewMode === 'list'
                  ? 'bg-oe-blue text-white'
                  : 'bg-surface-primary text-content-secondary hover:bg-surface-secondary',
              )}
              title={t('punch.view_list', { defaultValue: 'List view' })}
            >
              <LayoutList size={14} />
              <span className="hidden sm:inline">
                {t('punch.view_list', { defaultValue: 'List' })}
              </span>
            </button>
            <button
              onClick={() => setViewMode('kanban')}
              className={clsx(
                'flex items-center gap-1 px-3 py-2 text-sm transition-colors',
                viewMode === 'kanban'
                  ? 'bg-oe-blue text-white'
                  : 'bg-surface-primary text-content-secondary hover:bg-surface-secondary',
              )}
              aria-label={t('punch.view_kanban', { defaultValue: 'Kanban view' })}
              title={t('punch.view_kanban', { defaultValue: 'Kanban view' })}
            >
              <Columns3 size={14} />
              <span className="hidden sm:inline">
                {t('punch.view_kanban', { defaultValue: 'Kanban' })}
              </span>
            </button>
          </div>
        </div>
      </div>

      {/* Collapsible filters */}
      {showFilters && (
        <div className="flex flex-wrap gap-3 animate-fade-in">
          <select
            value={filterPriority}
            onChange={(e) => setFilterPriority(e.target.value as PunchPriority | '')}
            aria-label={t('punch.all_priorities', { defaultValue: 'All Priorities' })}
            className={inputCls + ' max-w-[160px]'}
          >
            <option value="">
              {t('punch.all_priorities', { defaultValue: 'All Priorities' })}
            </option>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {t(`punch.priority_${p}`, {
                  defaultValue: p.charAt(0).toUpperCase() + p.slice(1),
                })}
              </option>
            ))}
          </select>

          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value as PunchStatus | '')}
            aria-label={t('punch.all_statuses', { defaultValue: 'All Statuses' })}
            className={inputCls + ' max-w-[160px]'}
          >
            <option value="">
              {t('punch.all_statuses', { defaultValue: 'All Statuses' })}
            </option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`punch.status_${s}`, {
                  defaultValue: s
                    .split('_')
                    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
                    .join(' '),
                })}
              </option>
            ))}
          </select>

          <select
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value as PunchCategory | '')}
            aria-label={t('punch.all_categories', { defaultValue: 'All Categories' })}
            className={inputCls + ' max-w-[160px]'}
          >
            <option value="">
              {t('punch.all_categories', { defaultValue: 'All Categories' })}
            </option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {t(`punch.category_${c}`, {
                  defaultValue: c
                    .split('_')
                    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
                    .join(' '),
                })}
              </option>
            ))}
          </select>

          <select
            value={filterAssignee}
            onChange={(e) => setFilterAssignee(e.target.value)}
            aria-label={t('punch.all_assignees', { defaultValue: 'All Assignees' })}
            className={inputCls + ' max-w-[180px]'}
          >
            <option value="">
              {t('punch.all_assignees', { defaultValue: 'All Assignees' })}
            </option>
            {teamMembers.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Content */}
      <div>
        {!projectId ? (
          <RequiresProject
            emptyHint={t('punch.no_project_desc', {
              defaultValue:
                'Select a project from the dropdown above to view and manage punch list items.',
            })}
          >{null}</RequiresProject>
        ) : isLoading ? (
          <SkeletonTable rows={6} columns={5} />
        ) : isError ? (
          <RecoveryCard error={error} onRetry={() => refetch()} />
        ) : filteredItems.length === 0 ? (
          <EmptyState
            icon={<ListChecks size={28} strokeWidth={1.5} />}
            title={
              searchQuery || filterPriority || filterStatus || filterCategory || filterAssignee
                ? t('punch.no_results_title', { defaultValue: 'No matching items' })
                : t('punch.empty_title', { defaultValue: 'No punch list items' })
            }
            description={
              searchQuery || filterPriority || filterStatus || filterCategory || filterAssignee
                ? t('punch.no_results_desc', {
                    defaultValue: 'Try adjusting your search or filter criteria.',
                  })
                : t('punch.empty_desc', {
                    defaultValue:
                      'Create punch list items to track deficiencies, snags, and outstanding work.',
                  })
            }
            action={
              !(searchQuery || filterPriority || filterStatus || filterCategory || filterAssignee)
                ? {
                    label: t('punch.new_item', { defaultValue: 'New Item' }),
                    onClick: () => setShowAddModal(true),
                  }
                : undefined
            }
          />
        ) : viewMode === 'kanban' ? (
          <KanbanView
            items={filteredItems}
            onTransition={handleTransition}
            onDelete={handleDelete}
          />
        ) : (
          <Card className="overflow-hidden">
            {/* Bulk-action bar — visible only when items are selected. */}
            {selectedIds.size > 0 && (
              <div className="flex items-center justify-between gap-3 px-4 py-2 border-b border-border-light bg-oe-blue/5">
                <span className="text-sm text-content-secondary">
                  {t('punch.selection_count', {
                    defaultValue: '{{count}} selected',
                    count: selectedIds.size,
                  })}
                </span>
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={clearSelection}
                    disabled={bulkCloseMut.isPending}
                  >
                    {t('common.cancel', { defaultValue: 'Cancel' })}
                  </Button>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={handleBulkClose}
                    disabled={bulkCloseMut.isPending}
                    icon={<CheckCircle2 size={14} />}
                  >
                    {bulkCloseMut.isPending
                      ? t('punch.bulk_closing', { defaultValue: 'Closing...' })
                      : t('punch.bulk_close', {
                          defaultValue: 'Close selected ({{count}})',
                          count: selectedIds.size,
                        })}
                  </Button>
                </div>
              </div>
            )}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-light bg-surface-secondary/50">
                    <th className="px-3 py-3 text-left w-8">
                      <input
                        type="checkbox"
                        aria-label={t('punch.select_all', { defaultValue: 'Select all' })}
                        checked={
                          filteredItems.length > 0 &&
                          filteredItems.every((it) => selectedIds.has(it.id))
                        }
                        onChange={(e) => {
                          if (e.target.checked) {
                            setSelectedIds(new Set(filteredItems.map((it) => it.id)));
                          } else {
                            setSelectedIds(new Set());
                          }
                        }}
                        className="h-4 w-4 rounded border-border accent-oe-blue cursor-pointer"
                      />
                    </th>
                    <th className="px-4 py-3 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                      {t('punch.col_title', { defaultValue: 'Title' })}
                    </th>
                    <th className="px-4 py-3 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                      {t('punch.col_priority', { defaultValue: 'Priority' })}
                    </th>
                    <th className="px-4 py-3 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                      {t('punch.col_status', { defaultValue: 'Status' })}
                    </th>
                    <th className="px-4 py-3 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                      {t('punch.col_category', { defaultValue: 'Category' })}
                    </th>
                    <th className="px-4 py-3 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                      {t('punch.col_assigned_to', { defaultValue: 'Assigned To' })}
                    </th>
                    <th className="px-4 py-3 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                      {t('punch.col_due_date', { defaultValue: 'Due Date' })}
                    </th>
                    <th className="px-4 py-3 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                      {t('punch.col_photos', { defaultValue: 'Photos' })}
                    </th>
                    <th className="px-4 py-3 text-right text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                      {t('common.actions', { defaultValue: 'Actions' })}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-light">
                  {filteredItems.map((item) => (
                    <PunchTableRow
                      key={item.id}
                      item={item}
                      onTransition={handleTransition}
                      onDelete={handleDelete}
                      selected={selectedIds.has(item.id)}
                      onToggleSelect={toggleSelect}
                      highlight={highlightId === item.id}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </div>

      {/* Add modal */}
      {showAddModal && (
        <AddPunchModal
          onClose={() => setShowAddModal(false)}
          onSubmit={handleCreateSubmit}
          isPending={createMut.isPending}
          teamMembers={teamMembers}
        />
      )}

      <ConfirmDialog {...confirmProps} />

      {/* Mobile PWA — Slice 1. Bottom-anchored quick-action FAB visible
          only on viewports ≤640px. ≥44×44 tap target. */}
      <button
        type="button"
        onClick={() => setShowAddModal(true)}
        disabled={!projectId}
        aria-label={t('punch.new_item', { defaultValue: 'New Item' })}
        className="fixed bottom-5 right-5 z-40 inline-flex h-14 w-14 min-h-[44px] min-w-[44px] items-center justify-center rounded-full bg-oe-blue text-white shadow-lg ring-1 ring-black/5 transition-transform hover:scale-105 active:scale-95 disabled:opacity-50 disabled:hover:scale-100 sm:hidden"
      >
        <Plus size={22} />
      </button>
    </div>
  );
}

/* ── Table Row ─────────────────────────────────────────────────────────── */

const PunchTableRow = React.memo(function PunchTableRow({
  item,
  onTransition,
  onDelete,
  selected,
  onToggleSelect,
  highlight,
}: {
  item: PunchItem;
  onTransition: (id: string, status: PunchStatus) => void;
  onDelete: (id: string) => void;
  selected: boolean;
  onToggleSelect: (id: string) => void;
  /** When set (from a ?highlight deep-link) the row scrolls into view and
   *  flashes a highlight ring. */
  highlight?: boolean;
}) {
  const { t } = useTranslation();
  const transitions = STATUS_TRANSITION[item.status] ?? [];
  const rowRef = useRef<HTMLTableRowElement>(null);
  const [flash, setFlash] = useState(false);

  useEffect(() => {
    if (!highlight) return;
    setFlash(true);
    rowRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const timer = window.setTimeout(() => setFlash(false), 2400);
    return () => window.clearTimeout(timer);
  }, [highlight]);

  const isOverdue =
    item.due_date &&
    item.status !== 'closed' &&
    item.status !== 'verified' &&
    new Date(item.due_date) < new Date();

  const formattedDueDate = useMemo(() => {
    if (!item.due_date) return '-';
    try {
      return new Date(item.due_date).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      });
    } catch {
      return item.due_date;
    }
  }, [item.due_date]);

  return (
    <tr
      ref={rowRef}
      className={clsx(
        'transition-colors scroll-mt-24',
        flash && 'ring-2 ring-inset ring-oe-blue/50',
        flash
          ? 'bg-oe-blue/10'
          : selected
          ? 'bg-oe-blue/5 hover:bg-oe-blue/10'
          : isOverdue
          ? 'bg-red-50/40 hover:bg-red-50/70 dark:bg-red-950/10 dark:hover:bg-red-950/20'
          : 'hover:bg-surface-secondary/50',
      )}
    >
      <td className="px-3 py-3 w-8">
        <input
          type="checkbox"
          aria-label={t('punch.select_row', { defaultValue: 'Select row' })}
          checked={selected}
          onChange={() => onToggleSelect(item.id)}
          className="h-4 w-4 rounded border-border accent-oe-blue cursor-pointer"
        />
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          {isOverdue && (
            <AlertTriangle size={14} className="text-semantic-error shrink-0" />
          )}
          <span className="text-sm font-medium text-content-primary truncate max-w-[250px]">
            {item.title}
          </span>
        </div>
        {(item.location_x != null || item.location_y != null) && (
          <p className="text-xs text-content-tertiary mt-0.5 truncate max-w-[250px]">
            {`(${item.location_x ?? '-'}, ${item.location_y ?? '-'})`}
          </p>
        )}
        <PunchSourceBadge item={item} className="mt-0.5 inline-block" />
      </td>
      <td className="px-4 py-3">
        <Badge variant={PRIORITY_BADGE_VARIANT[item.priority]} size="sm" className={PRIORITY_BADGE_CLS[item.priority]}>
          {t(`punch.priority_${item.priority}`, {
            defaultValue: item.priority.charAt(0).toUpperCase() + item.priority.slice(1),
          })}
        </Badge>
      </td>
      <td className="px-4 py-3">
        <Badge variant={STATUS_BADGE_VARIANT[item.status]} size="sm">
          {t(`punch.status_${item.status}`, {
            defaultValue: item.status
              .split('_')
              .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
              .join(' '),
          })}
        </Badge>
      </td>
      <td className="px-4 py-3 text-sm text-content-secondary">
        {item.category
          ? t(`punch.category_${item.category}`, {
              defaultValue: item.category
                .split('_')
                .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
                .join(' '),
            })
          : '-'}
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          {item.assigned_to ? (
            <>
              <div className="h-6 w-6 rounded-full bg-oe-blue/10 text-oe-blue flex items-center justify-center text-xs font-semibold shrink-0">
                {item.assigned_to.charAt(0).toUpperCase()}
              </div>
              <span className="text-sm text-content-secondary truncate max-w-[100px]">
                {item.assigned_to}
              </span>
            </>
          ) : (
            <span className="text-sm text-content-quaternary">
              {t('punch.unassigned', { defaultValue: 'Unassigned' })}
            </span>
          )}
        </div>
      </td>
      <td className="px-4 py-3">
        <span
          className={clsx(
            'text-sm tabular-nums',
            isOverdue ? 'text-semantic-error font-medium' : 'text-content-secondary',
          )}
        >
          {formattedDueDate}
        </span>
        {isOverdue && (
          <div className="flex items-center gap-1 text-2xs text-semantic-error mt-0.5">
            <Clock size={10} />
            {t('punch.overdue', { defaultValue: 'Overdue' })}
          </div>
        )}
      </td>
      <td className="px-4 py-3 text-sm text-content-secondary tabular-nums">
        {(item.photos || []).length > 0 ? (
          <div className="flex items-center gap-1">
            <Camera size={14} className="text-content-tertiary" />
            {(item.photos || []).length}
          </div>
        ) : (
          '-'
        )}
      </td>
      <td className="px-4 py-3 text-right">
        <div className="flex items-center justify-end gap-1 flex-nowrap">
          {transitions.map((tr) => {
            const Icon = tr.icon;
            return (
              <button
                key={tr.next}
                onClick={() => onTransition(item.id, tr.next)}
                aria-label={t(tr.labelKey, { defaultValue: tr.defaultLabel })}
                title={t(tr.labelKey, { defaultValue: tr.defaultLabel })}
                className="inline-flex items-center gap-1 whitespace-nowrap rounded-md px-2 py-1 text-xs text-content-secondary hover:text-content-primary hover:bg-surface-secondary transition-colors"
              >
                <Icon size={12} className="shrink-0" />
                <span className="hidden xl:inline">
                  {t(tr.labelKey, { defaultValue: tr.defaultLabel })}
                </span>
              </button>
            );
          })}
          <button
            onClick={() => onDelete(item.id)}
            className="inline-flex items-center rounded-md p-1 text-content-quaternary hover:text-semantic-error hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
            aria-label={t('common.delete', { defaultValue: 'Delete' })}
            title={t('common.delete', { defaultValue: 'Delete' })}
          >
            <Trash2 size={13} />
          </button>
        </div>
      </td>
    </tr>
  );
});

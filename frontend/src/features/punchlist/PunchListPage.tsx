import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
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
  X,
  Play,
  CheckCircle2,
  ShieldCheck,
  XCircle,
  AlertTriangle,
  Clock,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb } from '@/shared/ui';
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
  resolved: [
    { next: 'verified', labelKey: 'punch.action_verify', defaultLabel: 'Verify', icon: ShieldCheck },
    { next: 'in_progress', labelKey: 'punch.action_reopen', defaultLabel: 'Reopen', icon: XCircle },
  ],
  verified: [
    { next: 'closed', labelKey: 'punch.action_close', defaultLabel: 'Close', icon: CheckCircle2 },
  ],
  closed: [],
};

/* ── Styling helpers ──────────────────────────────────────────────────── */

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

type ViewMode = 'list' | 'kanban';

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
      cls: 'text-[#b45309]',
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
    <div className="grid grid-cols-3 lg:grid-cols-6 gap-4">
      {items.map((item) => (
        <Card key={item.label} className="p-4 animate-card-in">
          <p className="text-2xs text-content-tertiary uppercase tracking-wide">{item.label}</p>
          <p className={clsx('text-xl font-bold mt-1 tabular-nums', item.cls)}>
            {item.value}
          </p>
        </Card>
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

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in">
      <div className="w-full max-w-2xl bg-surface-primary rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('punch.add_item', { defaultValue: 'Add Punch Item' })}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('punch.add_item', { defaultValue: 'Add Punch Item' })}
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
          {/* Title — full width */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('punch.field_title', { defaultValue: 'Title' })} <span className="text-semantic-error">*</span>
            </label>
            <input
              value={form.title}
              onChange={(e) => { set('title', e.target.value); setTouched(true); }}
              placeholder={t('punch.title_placeholder', {
                defaultValue: 'e.g. Missing fire seal on Level 3 penetration',
              })}
              className={clsx(inputCls, titleError && 'border-semantic-error focus:ring-red-300 focus:border-semantic-error')}
              autoFocus
            />
            {titleError && (
              <p className="mt-1 text-xs text-semantic-error">
                {t('punch.title_required', { defaultValue: 'Title is required' })}
              </p>
            )}
          </div>

          {/* Description — full width */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('punch.field_description', { defaultValue: 'Description' })}
            </label>
            <textarea
              value={form.description}
              onChange={(e) => set('description', e.target.value)}
              rows={2}
              className={textareaCls}
              placeholder={t('punch.description_placeholder', {
                defaultValue: 'Provide details about the issue...',
              })}
            />
          </div>

          {/* Priority — inline colored radio buttons in one row */}
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-2">
              {t('punch.field_priority', { defaultValue: 'Priority' })}
            </label>
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
          </div>

          {/* Two-column grid: Category + Assigned To */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Category */}
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('punch.field_category', { defaultValue: 'Category' })}
              </label>
              <select
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
            </div>

            {/* Assigned To */}
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('punch.field_assigned_to', { defaultValue: 'Assigned To' })}
              </label>
              <select
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
            </div>
          </div>

          {/* Two-column grid: Due Date + Location */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Due Date */}
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('punch.field_due_date', { defaultValue: 'Due Date' })}
              </label>
              <input
                type="date"
                value={form.due_date}
                onChange={(e) => set('due_date', e.target.value)}
                className={inputCls}
              />
            </div>

            {/* Location */}
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('punch.field_location', { defaultValue: 'Location' })}
              </label>
              <input
                value={form.location}
                onChange={(e) => set('location', e.target.value)}
                placeholder={t('punch.location_placeholder', {
                  defaultValue: 'e.g. Building A, Level 3, Room 305',
                })}
                className={inputCls}
              />
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={handleSubmit}
            disabled={isPending}
          >
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <Plus size={16} className="mr-1.5 shrink-0" />
            )}
            <span>{t('punch.create_item', { defaultValue: 'Create Item' })}</span>
          </Button>
        </div>
      </div>
    </div>
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

      {/* Source badge */}
      {item.metadata?.source === 'inspection' && (
        <div className="mt-1">
          <Badge variant="blue" size="sm">
            {t('punch.source_inspection', { defaultValue: 'From Inspection' })}
          </Badge>
        </div>
      )}
      {item.metadata?.source === 'ncr' && (
        <div className="mt-1">
          <Badge variant="warning" size="sm">
            {t('punch.source_ncr', { defaultValue: 'From NCR' })}
          </Badge>
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
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // State
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [showAddModal, setShowAddModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterPriority, setFilterPriority] = useState<PunchPriority | ''>('');
  const [filterStatus, setFilterStatus] = useState<PunchStatus | ''>('');
  const [filterCategory, setFilterCategory] = useState<PunchCategory | ''>('');
  const [filterAssignee, setFilterAssignee] = useState('');
  const [showFilters, setShowFilters] = useState(false);

  // Data queries
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const projectId = activeProjectId || projects[0]?.id || '';

  const { data: punchItems = [], isLoading } = useQuery({
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
          status: vars.status.replace('_', ' '),
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
    (id: string) => {
      delMut.mutate(id);
    },
    [delMut],
  );

  return (
    <div className="mx-auto max-w-7xl px-6 py-6 animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          { label: t('punch.title', { defaultValue: 'Punch List' }) },
        ]}
      />

      {/* ── Header: single compact row ─────────────────────────────────── */}
      <div className="mt-3 flex items-center justify-between gap-3 flex-nowrap overflow-x-auto">
        {/* Left: title */}
        <h1 className="text-lg font-bold text-content-primary flex items-center gap-2 shrink-0">
          <ListChecks size={20} className="text-oe-blue" />
          {t('punch.title', { defaultValue: 'Punch List' })}
        </h1>

        {/* Right: controls */}
        <div className="flex items-center gap-2 shrink-0">
          {/* Project selector */}
          {projects.length > 0 && (
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
                {t('punch.select_project', { defaultValue: 'Project...' })}
              </option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
          <Button variant="primary" size="sm" onClick={() => setShowAddModal(true)} disabled={!projectId} className="shrink-0 whitespace-nowrap" icon={<Plus size={14} />}>
            {t('punch.new_item', { defaultValue: 'New Item' })}
          </Button>
        </div>
      </div>

      {/* Stats */}
      <div className="mt-6">
        <StatsCards summary={summary} />
      </div>

      {/* Toolbar */}
      <div className="mt-6 flex flex-col sm:flex-row sm:items-center gap-3">
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
        <div className="mt-3 flex flex-wrap gap-3 animate-fade-in">
          <select
            value={filterPriority}
            onChange={(e) => setFilterPriority(e.target.value as PunchPriority | '')}
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
      <div className="mt-6">
        {!projectId ? (
          <EmptyState
            icon={<ListChecks size={28} strokeWidth={1.5} />}
            title={t('punch.no_project_title', { defaultValue: 'No project selected' })}
            description={t('punch.no_project_desc', {
              defaultValue:
                'Select a project from the dropdown above to view and manage punch list items.',
            })}
          />
        ) : isLoading ? (
          <div className="flex items-center justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-oe-blue border-t-transparent" />
          </div>
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
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-light bg-surface-secondary/50">
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
    </div>
  );
}

/* ── Table Row ─────────────────────────────────────────────────────────── */

const PunchTableRow = React.memo(function PunchTableRow({
  item,
  onTransition,
  onDelete,
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
    <tr className={clsx(
      'transition-colors',
      isOverdue
        ? 'bg-red-50/40 hover:bg-red-50/70 dark:bg-red-950/10 dark:hover:bg-red-950/20'
        : 'hover:bg-surface-secondary/50',
    )}>
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
        {item.metadata?.source === 'inspection' && (
          <Badge variant="blue" size="sm" className="mt-0.5">
            {t('punch.source_inspection', { defaultValue: 'From Inspection' })}
          </Badge>
        )}
        {item.metadata?.source === 'ncr' && (
          <Badge variant="warning" size="sm" className="mt-0.5">
            {t('punch.source_ncr', { defaultValue: 'From NCR' })}
          </Badge>
        )}
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
            className="inline-flex items-center rounded-md p-1 text-content-quaternary hover:text-semantic-error hover:bg-red-50 transition-colors"
            title={t('common.delete', { defaultValue: 'Delete' })}
          >
            <Trash2 size={13} />
          </button>
        </div>
      </td>
    </tr>
  );
});

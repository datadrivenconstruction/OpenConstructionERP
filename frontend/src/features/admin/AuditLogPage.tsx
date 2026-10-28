// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Audit Log Page — read-only timeline of every audit-bearing change in
 * the system.  Gated on the backend by `audit.view` (Manager+) and
 * exposed in the sidebar's Admin group when the JWT role is admin or
 * manager (the SidebarItem-gated check mirrors backend perms).
 *
 * Surface (v4.3.2+):
 *   • Full-width layout mirroring PermissionsMatrixPage glass styling.
 *   • Server-side pagination (default limit=50) with a total-rows
 *     indicator pulled from `/v1/audit/count`.
 *   • Filter bar:
 *       - user picker (autocomplete from /v1/users/)
 *       - module/entity dropdown
 *       - action free-text with datalist hints
 *       - date range with quick-preset chips (Today / 7d / 30d / Custom)
 *       - free-text search (client-side across action, entity, IP,
 *         actor display, JSON details)
 *       - severity heuristic chips (info / warning / critical — backend
 *         does not emit a severity column, so this is derived from the
 *         action verb on the client)
 *   • Sortable timestamp column (asc/desc toggle).
 *   • Drill-down drawer with side-by-side before/after JSON diff
 *     (hand-rolled to avoid a `react-diff-view` dependency).
 *   • CSV + JSON export of the current page (client-side render).
 *   • Touch-friendly: rows ≥56px, large tap targets, responsive grid.
 *
 * Backend params that we deliberately do NOT expose yet (no server
 * support):
 *   - project filter (audit table has no project_id column; entity_id
 *     can vary by module, so a true project scope needs a backend
 *     join — punted to a later release).
 *   - action multiselect (backend takes a single `action` string —
 *     expanding to multi would require an `action IN (…)` clause).
 *   - entity-type multiselect (same reason).
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import {
  AlertCircle,
  ArrowDownAZ,
  ArrowUpAZ,
  Calendar as CalendarIcon,
  ChevronLeft,
  ChevronRight,
  Clock,
  Download,
  Eye,
  FileJson,
  Filter,
  History as HistoryIcon,
  Search,
  ShieldAlert,
  ShieldCheck,
  User as UserIcon,
  X,
} from 'lucide-react';
import { Badge, EmptyState, Breadcrumb, DismissibleInfo, IntroRichText, Button, ModuleGuideButton } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { adminGuide } from './adminGuide';
import { useToastStore } from '@/stores/useToastStore';
import { triggerDownload } from '@/shared/lib/api';
import { fetchUsers, type User } from '@/features/users/api';
import {
  countAuditEntries,
  listAuditEntries,
  type AuditEntry,
  type AuditFilters,
  WELL_KNOWN_ENTITY_TYPES,
  WELL_KNOWN_ACTIONS,
} from './api';
import { fmtList, getIntlLocale } from '@/shared/lib/formatters';

const DEFAULT_LIMIT = 50;
const LIMIT_OPTIONS = [25, 50, 100, 200] as const;

/** Map common audit actions to a severity bucket for the chip filter. */
type Severity = 'info' | 'warning' | 'critical';
const SEVERITY_BY_ACTION: Record<string, Severity> = {
  create: 'info',
  update: 'info',
  login: 'info',
  logout: 'info',
  export: 'info',
  import: 'info',
  enable: 'info',
  approve: 'info',
  status_changed: 'info',
  reject: 'warning',
  disable: 'warning',
  archive: 'warning',
  delete: 'critical',
  restore: 'warning',
};

function severityOf(action: string): Severity {
  const key = action.toLowerCase();
  return SEVERITY_BY_ACTION[key] ?? 'info';
}

function severityBadgeVariant(sev: Severity): 'neutral' | 'blue' | 'warning' | 'error' {
  if (sev === 'critical') return 'error';
  if (sev === 'warning') return 'warning';
  return 'blue';
}

/** Format an ISO timestamp into a locale-friendly "MMM d, HH:mm:ss" string. */
function formatTimestamp(iso: string | null): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString(getIntlLocale(), {
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return iso;
  }
}

/** Lookup helper for the user picker — populates the user_id → email map. */
function buildUserMap(users: User[] | undefined): Map<string, User> {
  const m = new Map<string, User>();
  for (const u of users ?? []) m.set(u.id, u);
  return m;
}

/** Pull "before"/"after" payload shapes from the details column.
 *  Audit emitters do not all agree on a single shape, so we try a few
 *  well-known keys before falling back to "raw details".  All branches
 *  return a tuple so the caller can render a single side-by-side panel. */
function extractDiff(details: Record<string, unknown> | null): {
  before: unknown;
  after: unknown;
  raw: Record<string, unknown> | null;
} {
  if (!details) return { before: null, after: null, raw: null };
  const d = details as Record<string, unknown>;
  if ('before' in d || 'after' in d) {
    return { before: d.before ?? null, after: d.after ?? null, raw: d };
  }
  if ('old' in d || 'new' in d) {
    return { before: d.old ?? null, after: d.new ?? null, raw: d };
  }
  return { before: null, after: null, raw: d };
}

function toCsvCell(value: unknown): string {
  if (value == null) return '';
  const s = typeof value === 'string' ? value : JSON.stringify(value);
  const needsQuote = /[",\n\r]/.test(s);
  const escaped = s.replace(/"/g, '""');
  return needsQuote ? `"${escaped}"` : escaped;
}

function entriesToCsv(entries: AuditEntry[], userMap: Map<string, User>): string {
  const header = [
    'created_at',
    'action',
    'entity_type',
    'entity_id',
    'user_id',
    'user_email',
    'ip_address',
    'details',
  ];
  const rows = entries.map((e) => {
    const u = e.user_id ? userMap.get(e.user_id) : null;
    return [
      toCsvCell(e.created_at),
      toCsvCell(e.action),
      toCsvCell(e.entity_type),
      toCsvCell(e.entity_id),
      toCsvCell(e.user_id),
      toCsvCell(u?.email ?? ''),
      toCsvCell(e.ip_address),
      toCsvCell(e.details ?? {}),
    ].join(',');
  });
  return [header.join(','), ...rows].join('\r\n');
}

function entriesToJson(entries: AuditEntry[], userMap: Map<string, User>): string {
  // Re-shape so the export is self-contained — actor email materialised
  // alongside the raw user_id so downstream tools don't need a join.
  const rows = entries.map((e) => {
    const u = e.user_id ? userMap.get(e.user_id) : null;
    return {
      ...e,
      actor_email: u?.email ?? null,
      actor_full_name: u?.full_name ?? null,
    };
  });
  return JSON.stringify(rows, null, 2);
}

/* ── date-range presets ─────────────────────────────────────────────── */

type DatePresetId = 'all' | 'today' | 'last7' | 'last30' | 'custom';

interface DatePresetRange {
  from: string | null;
  to: string | null;
}

function dateRangeForPreset(id: DatePresetId): DatePresetRange | null {
  if (id === 'custom') return null;
  const now = new Date();
  if (id === 'all') return { from: null, to: null };
  const to = now.toISOString();
  if (id === 'today') {
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    return { from: start.toISOString(), to };
  }
  if (id === 'last7') {
    const start = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    return { from: start.toISOString(), to };
  }
  if (id === 'last30') {
    const start = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
    return { from: start.toISOString(), to };
  }
  return { from: null, to: null };
}

/* ── filter bar ─────────────────────────────────────────────────────── */

interface FilterBarProps {
  draft: AuditFilters;
  severity: Severity | 'all';
  searchText: string;
  preset: DatePresetId;
  users: User[] | undefined;
  onSeverity: (s: Severity | 'all') => void;
  onChange: (next: AuditFilters) => void;
  onSearchText: (text: string) => void;
  onPresetChange: (preset: DatePresetId) => void;
  onReset: () => void;
}

function FilterBar({
  draft,
  severity,
  searchText,
  preset,
  users,
  onSeverity,
  onChange,
  onSearchText,
  onPresetChange,
  onReset,
}: FilterBarProps) {
  const { t } = useTranslation();
  const [userQuery, setUserQuery] = useState('');
  const [userOpen, setUserOpen] = useState(false);

  const filteredUsers = useMemo(() => {
    const q = userQuery.trim().toLowerCase();
    const list = users ?? [];
    if (!q) return list.slice(0, 12);
    return list
      .filter(
        (u) =>
          u.email.toLowerCase().includes(q) ||
          (u.full_name ?? '').toLowerCase().includes(q),
      )
      .slice(0, 12);
  }, [users, userQuery]);

  const selectedUser = useMemo(
    () => (draft.userId ? users?.find((u) => u.id === draft.userId) : undefined),
    [users, draft.userId],
  );

  const sevChips: Array<{ id: Severity | 'all'; label: string; icon: typeof ShieldCheck }> = [
    { id: 'all', label: t('audit.severity_all', { defaultValue: 'All' }), icon: Filter },
    { id: 'info', label: t('audit.severity_info', { defaultValue: 'Info' }), icon: ShieldCheck },
    { id: 'warning', label: t('audit.severity_warning', { defaultValue: 'Warning' }), icon: ShieldAlert },
    { id: 'critical', label: t('audit.severity_critical', { defaultValue: 'Critical' }), icon: AlertCircle },
  ];

  const presetChips: Array<{ id: DatePresetId; label: string }> = [
    { id: 'all', label: t('audit.preset_all', { defaultValue: 'All time' }) },
    { id: 'today', label: t('audit.preset_today', { defaultValue: 'Today' }) },
    { id: 'last7', label: t('audit.preset_last7', { defaultValue: 'Last 7d' }) },
    { id: 'last30', label: t('audit.preset_last30', { defaultValue: 'Last 30d' }) },
    { id: 'custom', label: t('audit.preset_custom', { defaultValue: 'Custom' }) },
  ];

  return (
    <div className="relative overflow-hidden rounded-2xl border border-white/40 bg-white/60 backdrop-blur-xl shadow-sm dark:border-white/5 dark:bg-slate-900/40">
      <div className="p-4 grid gap-3 md:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
        {/* Free-text search — first column, spans two on wide screens */}
        <div className="xl:col-span-2">
          <label
            htmlFor="audit-search"
            className="block text-xs font-medium text-content-secondary mb-1"
          >
            {t('audit.search_label', { defaultValue: 'Search' })}
          </label>
          <div className="relative">
            <Search className="absolute start-2.5 top-1/2 -translate-y-1/2 text-content-tertiary" size={14} />
            <input
              id="audit-search"
              type="search"
              value={searchText}
              onChange={(e) => onSearchText(e.target.value)}
              placeholder={t('audit.search_placeholder', {
                defaultValue: 'Search actor, entity, IP, payload…',
              })}
              data-testid="audit-search"
              className="h-9 w-full rounded-lg border border-border bg-surface-primary ps-8 pe-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            />
          </div>
        </div>

        {/* User picker */}
        <div className="relative">
          <label className="block text-xs font-medium text-content-secondary mb-1">
            {t('audit.filter_user', { defaultValue: 'User' })}
          </label>
          <div className="relative">
            <UserIcon className="absolute start-2.5 top-1/2 -translate-y-1/2 text-content-tertiary" size={14} />
            <input
              type="text"
              role="combobox"
              aria-expanded={userOpen}
              aria-label={t('audit.filter_user', { defaultValue: 'User' })}
              value={selectedUser ? selectedUser.email : userQuery}
              placeholder={t('audit.filter_user_placeholder', { defaultValue: 'Search by email or name…' })}
              onFocus={() => setUserOpen(true)}
              onBlur={() => window.setTimeout(() => setUserOpen(false), 150)}
              onChange={(e) => {
                setUserQuery(e.target.value);
                if (draft.userId) onChange({ ...draft, userId: null });
              }}
              className="h-9 w-full rounded-lg border border-border bg-surface-primary ps-8 pe-8 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            />
            {(draft.userId || userQuery) && (
              <button
                type="button"
                onClick={() => {
                  setUserQuery('');
                  onChange({ ...draft, userId: null });
                }}
                aria-label={t('common.clear', { defaultValue: 'Clear' })}
                className="absolute end-2 top-1/2 -translate-y-1/2 text-content-tertiary hover:text-content-primary"
              >
                <X size={14} />
              </button>
            )}
          </div>
          {userOpen && filteredUsers.length > 0 && (
            <ul
              role="listbox"
              className="absolute z-20 mt-1 max-h-60 w-full overflow-auto rounded-lg border border-border bg-surface-primary shadow-lg"
            >
              {filteredUsers.map((u) => (
                <li key={u.id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={draft.userId === u.id}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      setUserQuery('');
                      setUserOpen(false);
                      onChange({ ...draft, userId: u.id });
                    }}
                    className="block w-full px-3 py-2 text-left text-sm hover:bg-surface-secondary"
                  >
                    <div className="font-medium">{u.full_name || u.email}</div>
                    <div className="text-xs text-content-tertiary">{u.email}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Module / entity-type */}
        <div>
          <label className="block text-xs font-medium text-content-secondary mb-1">
            {t('audit.filter_module', { defaultValue: 'Module / entity' })}
          </label>
          <select
            value={draft.entityType ?? ''}
            onChange={(e) => onChange({ ...draft, entityType: e.target.value || null })}
            className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            aria-label={t('audit.filter_module', { defaultValue: 'Module / entity' })}
          >
            <option value="">{t('audit.filter_module_all', { defaultValue: 'All entities' })}</option>
            {WELL_KNOWN_ENTITY_TYPES.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>

        {/* Action — free text with datalist hint */}
        <div>
          <label className="block text-xs font-medium text-content-secondary mb-1">
            {t('audit.filter_action', { defaultValue: 'Action' })}
          </label>
          <div className="relative">
            <Search className="absolute start-2.5 top-1/2 -translate-y-1/2 text-content-tertiary" size={14} />
            <input
              type="text"
              list="audit-action-suggestions"
              value={draft.action ?? ''}
              onChange={(e) => onChange({ ...draft, action: e.target.value || null })}
              placeholder={t('audit.filter_action_placeholder', { defaultValue: 'create, update, delete…' })}
              className="h-9 w-full rounded-lg border border-border bg-surface-primary ps-8 pe-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              aria-label={t('audit.filter_action', { defaultValue: 'Action' })}
            />
            <datalist id="audit-action-suggestions">
              {WELL_KNOWN_ACTIONS.map((a) => (
                <option key={a} value={a} />
              ))}
            </datalist>
          </div>
        </div>

        {/* Date range — from / to as two native date inputs (visible only when "custom") */}
        <div className={preset === 'custom' ? '' : 'opacity-60'}>
          <label className="block text-xs font-medium text-content-secondary mb-1">
            {t('audit.filter_from', { defaultValue: 'From' })}
          </label>
          <input
            type="date"
            value={draft.dateFrom ? draft.dateFrom.slice(0, 10) : ''}
            onChange={(e) => {
              onPresetChange('custom');
              onChange({ ...draft, dateFrom: e.target.value ? `${e.target.value}T00:00:00Z` : null });
            }}
            className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            aria-label={t('audit.filter_from', { defaultValue: 'From' })}
          />
        </div>

        <div className={preset === 'custom' ? '' : 'opacity-60'}>
          <label className="block text-xs font-medium text-content-secondary mb-1">
            {t('audit.filter_to', { defaultValue: 'To' })}
          </label>
          <input
            type="date"
            value={draft.dateTo ? draft.dateTo.slice(0, 10) : ''}
            onChange={(e) => {
              onPresetChange('custom');
              onChange({ ...draft, dateTo: e.target.value ? `${e.target.value}T23:59:59Z` : null });
            }}
            className="h-9 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            aria-label={t('audit.filter_to', { defaultValue: 'To' })}
          />
        </div>
      </div>

      {/* Quick-preset chips + severity chips */}
      <div className="flex flex-wrap items-center gap-2 px-4 pb-3">
        <span className="inline-flex items-center gap-1 text-xs font-medium text-content-secondary">
          <CalendarIcon size={12} />
          {t('audit.range_label', { defaultValue: 'Range' })}:
        </span>
        {presetChips.map((c) => {
          const active = preset === c.id;
          return (
            <button
              key={c.id}
              type="button"
              data-testid={`audit-preset-${c.id}`}
              aria-pressed={active}
              onClick={() => onPresetChange(c.id)}
              className={clsx(
                'inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition-colors',
                active
                  ? 'bg-oe-blue text-content-inverse border-oe-blue'
                  : 'border-border text-content-secondary hover:bg-surface-secondary',
              )}
            >
              {c.label}
            </button>
          );
        })}
      </div>

      {/* Severity chips + reset */}
      <div className="flex flex-wrap items-center gap-2 px-4 pb-4">
        <span className="text-xs font-medium text-content-secondary mr-1">
          {t('audit.severity', { defaultValue: 'Severity' })}:
        </span>
        {sevChips.map((c) => {
          const active = severity === c.id;
          const Icon = c.icon;
          return (
            <button
              key={c.id}
              type="button"
              aria-pressed={active}
              onClick={() => onSeverity(c.id)}
              className={clsx(
                'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors',
                active
                  ? 'bg-oe-blue text-content-inverse border-oe-blue'
                  : 'border-border text-content-secondary hover:bg-surface-secondary',
              )}
            >
              <Icon size={12} />
              {c.label}
            </button>
          );
        })}
        <div className="grow" />
        <button
          type="button"
          onClick={onReset}
          data-testid="audit-reset"
          className="text-xs text-content-secondary hover:text-content-primary underline-offset-2 hover:underline"
        >
          {t('audit.reset_filters', { defaultValue: 'Reset filters' })}
        </button>
      </div>
    </div>
  );
}

/* ── row ────────────────────────────────────────────────────────────── */

interface TimelineRowProps {
  entry: AuditEntry;
  user: User | undefined;
  onOpen: () => void;
}

function TimelineRow({ entry, user, onOpen }: TimelineRowProps) {
  const sev = severityOf(entry.action);
  const diff = extractDiff(entry.details);
  const hasDiff = diff.before !== null || diff.after !== null;
  return (
    <tr
      data-testid="audit-row"
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onOpen();
        }
      }}
      tabIndex={0}
      aria-label={`${entry.action} ${entry.entity_type}`}
      className={clsx(
        'group cursor-pointer border-b border-border-light bg-surface-primary',
        'hover:bg-surface-secondary focus:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-inset focus:ring-oe-blue/30',
      )}
    >
      <td className="whitespace-nowrap px-4 py-3 align-top min-h-[56px]">
        <span className="inline-flex items-center gap-1 font-mono text-xs text-content-tertiary">
          <Clock size={11} />
          {formatTimestamp(entry.created_at)}
        </span>
      </td>
      <td className="px-4 py-3 align-top">
        <Badge variant={severityBadgeVariant(sev)} className="shrink-0">
          {sev}
        </Badge>
      </td>
      <td className="px-4 py-3 align-top">
        <div className="min-w-0 text-sm">
          <div className="font-medium text-content-primary">
            {user ? user.full_name || user.email : entry.user_id ? `user:${entry.user_id.slice(0, 8)}` : 'system'}
          </div>
          {user?.email && (
            <div className="text-xs text-content-tertiary truncate">{user.email}</div>
          )}
          {entry.ip_address && (
            <div className="font-mono text-[11px] text-content-tertiary">{entry.ip_address}</div>
          )}
        </div>
      </td>
      <td className="px-4 py-3 align-top">
        <span className="font-medium text-sm">{entry.action}</span>
      </td>
      <td className="px-4 py-3 align-top">
        <div className="min-w-0">
          <div className="text-sm text-content-primary">{entry.entity_type}</div>
          {entry.entity_id && (
            <div className="font-mono text-[11px] text-content-tertiary truncate">
              #{entry.entity_id.slice(0, 12)}
            </div>
          )}
        </div>
      </td>
      <td className="px-4 py-3 align-top">
        <div className="flex items-center justify-between gap-2">
          <span
            className={clsx(
              'truncate text-xs text-content-tertiary',
              hasDiff ? 'italic' : '',
            )}
          >
            {hasDiff
              ? 'before/after available'
              : diff.raw
                ? fmtList(Object.keys(diff.raw).slice(0, 3))
                : '—'}
          </span>
          <Eye
            size={14}
            className="shrink-0 text-content-tertiary opacity-0 group-hover:opacity-100 group-focus:opacity-100 transition-opacity"
          />
        </div>
      </td>
    </tr>
  );
}

/* ── drawer ─────────────────────────────────────────────────────────── */

function JsonBlock({ data }: { data: unknown }) {
  let pretty: string;
  try {
    pretty = JSON.stringify(data ?? null, null, 2);
  } catch {
    pretty = String(data);
  }
  return (
    <pre className="m-0 overflow-auto rounded-md bg-surface-secondary p-3 text-xs leading-relaxed text-content-primary whitespace-pre-wrap break-words">
      {pretty}
    </pre>
  );
}

function DetailDrawer({
  entry,
  user,
  onClose,
}: {
  entry: AuditEntry;
  user: User | undefined;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const diff = extractDiff(entry.details);
  const hasDiff = diff.before !== null || diff.after !== null;

  // ESC to close — important for keyboard nav.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-40 flex"
      role="dialog"
      aria-modal="true"
      aria-label={t('audit.drawer_title', { defaultValue: 'Audit entry detail' })}
    >
      <div
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        data-testid="audit-drawer"
        className="relative ml-auto h-full w-full max-w-2xl overflow-y-auto bg-surface-primary shadow-xl"
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border bg-surface-primary px-4 py-3">
          <div className="min-w-0">
            <div className="text-xs text-content-tertiary">
              {formatTimestamp(entry.created_at)}
            </div>
            <div className="truncate font-medium">
              {entry.action} · {entry.entity_type}
              {entry.entity_id ? ` · ${entry.entity_id}` : ''}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
          >
            <X size={16} />
          </button>
        </div>
        <div className="space-y-4 p-4">
          <section>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
              {t('audit.actor', { defaultValue: 'Actor' })}
            </div>
            <div className="text-sm">
              {user ? (
                <>
                  <div>{user.full_name || user.email}</div>
                  <div className="text-xs text-content-tertiary">{user.email}</div>
                </>
              ) : entry.user_id ? (
                <span className="font-mono text-xs">{entry.user_id}</span>
              ) : (
                <span className="text-content-tertiary">
                  {t('audit.system', { defaultValue: 'System / background' })}
                </span>
              )}
              {entry.ip_address && (
                <div className="text-xs text-content-tertiary font-mono">{entry.ip_address}</div>
              )}
            </div>
          </section>

          {hasDiff ? (
            <section>
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                {t('audit.diff', { defaultValue: 'Before / after' })}
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <div className="mb-1 text-xs text-content-secondary">
                    {t('audit.before', { defaultValue: 'Before' })}
                  </div>
                  <JsonBlock data={diff.before} />
                </div>
                <div>
                  <div className="mb-1 text-xs text-content-secondary">
                    {t('audit.after', { defaultValue: 'After' })}
                  </div>
                  <JsonBlock data={diff.after} />
                </div>
              </div>
            </section>
          ) : null}

          <section>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
              {t('audit.raw_payload', { defaultValue: 'Raw payload' })}
            </div>
            <JsonBlock data={diff.raw} />
          </section>
        </div>
      </aside>
    </div>
  );
}

/* ── page ───────────────────────────────────────────────────────────── */

export function AuditLogPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);

  const initialFilters: AuditFilters = {
    limit: DEFAULT_LIMIT,
    offset: 0,
    sort: 'desc',
  };
  const [filters, setFilters] = useState<AuditFilters>(initialFilters);
  // `pending` holds the in-flight filter edits (action text, etc.) so we
  // can debounce them into `filters` without refetching on every keystroke.
  const [pending, setPending] = useState<AuditFilters>(initialFilters);
  const [severity, setSeverity] = useState<Severity | 'all'>('all');
  const [activeId, setActiveId] = useState<string | null>(null);
  const [preset, setPreset] = useState<DatePresetId>('all');
  const [searchText, setSearchText] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  // Debounce free-text search — typing into a 50-row table shouldn't
  // re-filter on every keystroke. 200ms keeps it snappy without being
  // noisy.
  useEffect(() => {
    const id = window.setTimeout(() => setDebouncedSearch(searchText), 200);
    return () => window.clearTimeout(id);
  }, [searchText]);

  // Debounce filter-bar edits → server params. 250ms feels live without
  // flooding the backend; preset / sort changes are flushed immediately
  // by their own handlers (they go through `setFilters` directly).
  useEffect(() => {
    const id = window.setTimeout(() => {
      setFilters((prev) => {
        const next = { ...pending, offset: 0 };
        // Cheap shallow-equality bail-out so we don't kick refetches that
        // produce identical payloads.
        if (
          prev.userId === next.userId &&
          prev.entityType === next.entityType &&
          prev.action === next.action &&
          prev.dateFrom === next.dateFrom &&
          prev.dateTo === next.dateTo &&
          prev.sort === next.sort &&
          prev.limit === next.limit
        ) {
          return prev;
        }
        return next;
      });
    }, 250);
    return () => window.clearTimeout(id);
  }, [pending]);

  const usersQuery = useQuery({
    queryKey: ['audit-log', 'users'],
    // Backend caps /v1/users/?limit at 100 (422 above it). The audit-log
    // page only uses this list to resolve user IDs to display names — 100
    // is plenty and avoids a 422 every time /admin/audit-log mounts.
    queryFn: () => fetchUsers({ limit: 100 }),
    staleTime: 60_000,
  });

  const entriesQuery = useQuery({
    queryKey: ['audit-log', 'entries', filters],
    queryFn: () => listAuditEntries(filters),
  });

  const countQuery = useQuery({
    queryKey: ['audit-log', 'count', {
      userId: filters.userId ?? null,
      entityType: filters.entityType ?? null,
      action: filters.action ?? null,
      dateFrom: filters.dateFrom ?? null,
      dateTo: filters.dateTo ?? null,
    }],
    queryFn: () =>
      countAuditEntries({
        userId: filters.userId,
        entityType: filters.entityType,
        action: filters.action,
        dateFrom: filters.dateFrom,
        dateTo: filters.dateTo,
      }),
    staleTime: 5_000,
  });

  const userMap = useMemo(() => buildUserMap(usersQuery.data), [usersQuery.data]);

  // Three-stage client-side filter: severity → free-text search.
  const filteredEntries = useMemo(() => {
    let list = entriesQuery.data ?? [];
    if (severity !== 'all') {
      list = list.filter((e) => severityOf(e.action) === severity);
    }
    const q = debouncedSearch.trim().toLowerCase();
    if (q) {
      list = list.filter((e) => {
        const u = e.user_id ? userMap.get(e.user_id) : null;
        const haystack = [
          e.action,
          e.entity_type,
          e.entity_id ?? '',
          e.user_id ?? '',
          e.ip_address ?? '',
          u?.email ?? '',
          u?.full_name ?? '',
          e.details ? JSON.stringify(e.details) : '',
        ]
          .join(' ')
          .toLowerCase();
        return haystack.includes(q);
      });
    }
    return list;
  }, [entriesQuery.data, severity, debouncedSearch, userMap]);

  /* ── filter / preset handlers ─────────────────────────────────────── */

  const handlePendingChange = useCallback((next: AuditFilters) => {
    // Routes to the debounced `pending` state — the effect above pushes
    // it into `filters` after a short idle window, so we don't issue a
    // GET per keystroke.
    setPending(next);
  }, []);

  const handlePresetChange = useCallback(
    (next: DatePresetId) => {
      setPreset(next);
      if (next === 'custom') return;
      const range = dateRangeForPreset(next);
      if (range) {
        // Flush both the pending and committed filter set so the change
        // is visible in the date inputs *and* fires the refetch
        // immediately — preset chips are meant to feel one-click.
        setPending((p) => ({ ...p, dateFrom: range.from, dateTo: range.to }));
        setFilters((f) => ({ ...f, dateFrom: range.from, dateTo: range.to, offset: 0 }));
      }
    },
    [],
  );

  const handleSort = useCallback(() => {
    setFilters((f) => ({ ...f, sort: f.sort === 'asc' ? 'desc' : 'asc', offset: 0 }));
    setPending((p) => ({ ...p, sort: p.sort === 'asc' ? 'desc' : 'asc' }));
  }, []);

  const resetFilters = useCallback(() => {
    const reset: AuditFilters = { limit: DEFAULT_LIMIT, offset: 0, sort: 'desc' };
    setFilters(reset);
    setPending(reset);
    setSeverity('all');
    setPreset('all');
    setSearchText('');
  }, []);

  const offset = filters.offset ?? 0;
  const limit = filters.limit ?? DEFAULT_LIMIT;
  const total = countQuery.data ?? null;
  const pageStart = (entriesQuery.data?.length ?? 0) > 0 ? offset + 1 : 0;
  const pageEnd = offset + (entriesQuery.data?.length ?? 0);
  const canPrev = offset > 0;
  const canNext =
    total != null
      ? pageEnd < total
      : (entriesQuery.data?.length ?? 0) >= limit;

  const handlePrev = useCallback(() => {
    setFilters((f) => ({ ...f, offset: Math.max(0, (f.offset ?? 0) - (f.limit ?? DEFAULT_LIMIT)) }));
  }, []);

  const handleNext = useCallback(() => {
    setFilters((f) => ({ ...f, offset: (f.offset ?? 0) + (f.limit ?? DEFAULT_LIMIT) }));
  }, []);

  const handleLimitChange = useCallback((next: number) => {
    setFilters((f) => ({ ...f, limit: next, offset: 0 }));
    setPending((p) => ({ ...p, limit: next }));
  }, []);

  const handleExportCsv = useCallback(() => {
    const list = filteredEntries;
    if (list.length === 0) {
      addToast({
        type: 'info',
        title: t('audit.export_empty', { defaultValue: 'Nothing to export' }),
      });
      return;
    }
    const csv = entriesToCsv(list, userMap);
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    triggerDownload(blob, `audit-log-${stamp}.csv`);
  }, [filteredEntries, userMap, addToast, t]);

  const handleExportJson = useCallback(() => {
    const list = filteredEntries;
    if (list.length === 0) {
      addToast({
        type: 'info',
        title: t('audit.export_empty', { defaultValue: 'Nothing to export' }),
      });
      return;
    }
    const json = entriesToJson(list, userMap);
    const blob = new Blob([json], { type: 'application/json;charset=utf-8' });
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    triggerDownload(blob, `audit-log-${stamp}.json`);
  }, [filteredEntries, userMap, addToast, t]);

  const activeEntry = useMemo(() => {
    if (!activeId) return null;
    return entriesQuery.data?.find((e) => e.id === activeId) ?? null;
  }, [activeId, entriesQuery.data]);

  /* ── render ─────────────────────────────────────────────────────── */

  const pagerLabel = useMemo(() => {
    if ((entriesQuery.data?.length ?? 0) === 0) {
      return t('audit.page_empty', { defaultValue: 'No entries on this page' });
    }
    if (total != null) {
      return t('audit.page_of_total', {
        defaultValue: 'Showing {{start}}–{{end}} of {{total}}',
        start: pageStart,
        end: pageEnd,
        total,
      });
    }
    return t('audit.page_of', {
      defaultValue: 'Showing {{start}}–{{end}}',
      start: pageStart,
      end: pageEnd,
    });
  }, [entriesQuery.data, total, pageStart, pageEnd, t]);

  const PageControls = (
    <div className="flex flex-wrap items-center justify-between gap-2 px-1">
      <span className="text-xs text-content-tertiary" data-testid="audit-pager-label">
        {pagerLabel}
      </span>
      <div className="flex items-center gap-2">
        <label className="text-xs text-content-tertiary inline-flex items-center gap-1">
          <span>{t('audit.page_size', { defaultValue: 'Rows' })}:</span>
          <select
            value={limit}
            onChange={(e) => handleLimitChange(Number(e.target.value))}
            className="h-7 rounded-md border border-border bg-surface-primary px-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            aria-label={t('audit.page_size', { defaultValue: 'Rows' })}
          >
            {LIMIT_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={handlePrev}
          disabled={!canPrev}
          aria-label={t('common.prev', { defaultValue: 'Previous page' })}
          className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <ChevronLeft size={14} />
        </button>
        <button
          type="button"
          onClick={handleNext}
          disabled={!canNext}
          aria-label={t('common.next', { defaultValue: 'Next page' })}
          className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );

  return (
    <div className="space-y-5 animate-fade-in" data-testid="audit-log-page">
      {/* Breadcrumb — single-item trail auto-hides (canonical top block). */}
      <Breadcrumb
        items={[{ label: t('admin.audit_log_title', { defaultValue: 'Audit Log' }) }]}
      />

      {/* Canonical header row — module name + icon live in the top app bar. */}
      <PageHeader
        srTitle={t('admin.audit_log_title', { defaultValue: 'Audit Log' })}
        subtitle={t('admin.audit_log_subtitle', {
          defaultValue:
            'Read-only timeline of every recorded change. Filter by user, module, action or date, open a row for the full payload.',
        })}
        actions={
          <>
            <ModuleGuideButton content={adminGuide} />
            <Button
              variant="secondary"
              size="sm"
              icon={<Download size={14} />}
              onClick={handleExportCsv}
              data-testid="audit-export-csv"
            >
              {t('audit.export_csv', { defaultValue: 'Export CSV' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<FileJson size={14} />}
              onClick={handleExportJson}
              data-testid="audit-export-json"
            >
              {t('audit.export_json', { defaultValue: 'Export JSON' })}
            </Button>
          </>
        }
      />

      {/* Canonical module intro — pain-named, copy from MODULE_INTRO_COPY. */}
      <DismissibleInfo
        storageKey="admin-audit-log"
        title={t('admin_audit_log.intro_title', {
          defaultValue: 'Prove who changed what, when',
        })}
        more={
          t('admin_audit_log.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('admin_audit_log.intro_more')} />
            : undefined
        }
        links={[
          { label: t('nav.users', { defaultValue: 'User Management' }), onClick: () => navigate('/users') },
          { label: t('nav.governance', { defaultValue: 'Governance' }), onClick: () => navigate('/governance') },
        ]}
      >
        {t('admin_audit_log.intro_body', {
          defaultValue:
            'A read-only, filterable timeline of every recorded action across the platform: who did it, on which record, and when. Use it to investigate a dispute or satisfy an audit; access is limited to Manager and above.',
        })}
      </DismissibleInfo>

      <FilterBar
          draft={pending}
          severity={severity}
          searchText={searchText}
          preset={preset}
          users={usersQuery.data}
          onSeverity={setSeverity}
          onChange={handlePendingChange}
          onSearchText={setSearchText}
          onPresetChange={handlePresetChange}
          onReset={resetFilters}
        />

        {PageControls}

        <div className="overflow-hidden rounded-2xl border border-white/40 bg-white/70 backdrop-blur-xl shadow-sm dark:border-white/5 dark:bg-slate-900/40">
          {entriesQuery.isLoading ? (
            <div className="divide-y divide-border-light" aria-busy="true">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 px-4 py-3 min-h-[56px]">
                  <div className="h-5 w-14 rounded-full bg-surface-secondary animate-pulse" />
                  <div className="flex-1 space-y-1">
                    <div className="h-3 w-2/3 rounded bg-surface-secondary animate-pulse" />
                    <div className="h-2.5 w-1/3 rounded bg-surface-secondary animate-pulse" />
                  </div>
                </div>
              ))}
            </div>
          ) : entriesQuery.isError ? (
            <div className="p-6">
              <EmptyState
                icon={<AlertCircle size={20} />}
                title={t('audit.error_title', { defaultValue: 'Could not load audit log' })}
                description={
                  entriesQuery.error instanceof Error
                    ? entriesQuery.error.message
                    : t('audit.error_generic', { defaultValue: 'Please try again or refine the filters.' })
                }
                action={{
                  label: t('common.retry'),
                  onClick: () => void entriesQuery.refetch(),
                }}
              />
            </div>
          ) : filteredEntries.length === 0 ? (
            <div className="p-6">
              <EmptyState
                icon={<HistoryIcon size={20} />}
                title={t('audit.empty_title', { defaultValue: 'No audit entries match these filters' })}
                description={t('audit.empty_desc', {
                  defaultValue: 'Adjust the filters above or extend the date range.',
                })}
                action={{
                  label: t('audit.reset_filters', { defaultValue: 'Reset filters' }),
                  onClick: resetFilters,
                }}
              />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-sm">
                <caption className="sr-only">
                  {t('admin.audit_log_title', { defaultValue: 'Audit Log' })}
                </caption>
                <thead className="bg-surface-secondary/50 text-xs uppercase tracking-wide text-content-tertiary">
                  <tr>
                    <th scope="col" className="px-4 py-2 text-left font-medium">
                      <button
                        type="button"
                        onClick={handleSort}
                        data-testid="audit-sort-timestamp"
                        className="inline-flex items-center gap-1 hover:text-content-primary"
                        aria-label={t('audit.sort_timestamp', { defaultValue: 'Sort by timestamp' })}
                        aria-sort={filters.sort === 'asc' ? 'ascending' : 'descending'}
                      >
                        {t('audit.col_timestamp', { defaultValue: 'Timestamp' })}
                        {filters.sort === 'asc' ? <ArrowUpAZ size={12} /> : <ArrowDownAZ size={12} />}
                      </button>
                    </th>
                    <th scope="col" className="px-4 py-2 text-left font-medium">
                      {t('audit.col_severity', { defaultValue: 'Severity' })}
                    </th>
                    <th scope="col" className="px-4 py-2 text-left font-medium">
                      {t('audit.col_actor', { defaultValue: 'Actor' })}
                    </th>
                    <th scope="col" className="px-4 py-2 text-left font-medium">
                      {t('audit.col_action', { defaultValue: 'Action' })}
                    </th>
                    <th scope="col" className="px-4 py-2 text-left font-medium">
                      {t('audit.col_target', { defaultValue: 'Target' })}
                    </th>
                    <th scope="col" className="px-4 py-2 text-left font-medium">
                      {t('audit.col_preview', { defaultValue: 'Preview' })}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {filteredEntries.map((entry) => (
                    <TimelineRow
                      key={entry.id}
                      entry={entry}
                      user={entry.user_id ? userMap.get(entry.user_id) : undefined}
                      onOpen={() => setActiveId(entry.id)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {PageControls}

        {activeEntry && (
          <DetailDrawer
            entry={activeEntry}
            user={activeEntry.user_id ? userMap.get(activeEntry.user_id) : undefined}
            onClose={() => setActiveId(null)}
          />
        )}
    </div>
  );
}

export default AuditLogPage;

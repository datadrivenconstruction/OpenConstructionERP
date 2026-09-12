// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/shared/lib/api';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  Clock,
  Download,
  ExternalLink,
  Filter,
  Search,
  User as UserIcon,
  X,
} from 'lucide-react';
import { Badge, EmptyState } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { fetchProjectTimeline, type TimelineEntry, type TimelineFilters } from './api';

const LIMIT = 50;

const ACTION_COLORS: Record<string, string> = {
  created: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300',
  updated: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300',
  deleted: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
  status_changed: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300',
  approved: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300',
  rejected: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300',
  submitted: 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/30 dark:text-indigo-300',
  imported: 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300',
};

function actionColor(action: string): string {
  for (const [key, cls] of Object.entries(ACTION_COLORS)) {
    if (action.toLowerCase().includes(key)) return cls;
  }
  return 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300';
}

function formatAction(action: string): string {
  return action
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function relativeTime(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  const now = Date.now();
  const diff = now - d.getTime();
  if (diff < 60_000) return 'just now';
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  if (diff < 604_800_000) return `${Math.floor(diff / 86_400_000)}d ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function fullDateTime(iso: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

/** Build a route path for the entity so clicking navigates there. */
function entityRoute(entry: TimelineEntry): string | null {
  if (!entry.entity_id || !entry.module) return null;
  const mod = entry.module.toLowerCase();
  // Map module names to routes
  const routeMap: Record<string, string> = {
    boq: 'boq', projects: 'projects', variations: 'variations',
    changeorders: 'changeorders', documents: 'documents', contracts: 'contracts',
    procurement: 'procurement', inspections: 'inspections', ncr: 'ncr',
    rfi: 'rfi', submittals: 'submittals', issues: 'issues', risks: 'risks',
    tasks: 'tasks', schedule: 'schedule', photos: 'photos',
  };
  const route = routeMap[mod];
  if (!route) return null;
  return `/${route}/${entry.entity_id}`;
}

const ACTION_OPTIONS = [
  'created', 'updated', 'deleted', 'status_changed',
  'approved', 'rejected', 'submitted', 'imported',
];

export function TimelinePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const activeProjectId = useProjectContextStore((s: { activeProjectId: string | null }) => s.activeProjectId);
  const projectId = routeProjectId || activeProjectId;

  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState('');
  const [moduleFilter, setModuleFilter] = useState('');
  const [actionFilter, setActionFilter] = useState('');
  const [sinceFilter, setSinceFilter] = useState('');
  const [untilFilter, setUntilFilter] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [selectedEntry, setSelectedEntry] = useState<TimelineEntry | null>(null);
  const [filters, setFilters] = useState<TimelineFilters>({});

  const { data, isLoading, error } = useQuery({
    queryKey: ['timeline', projectId, filters, offset],
    queryFn: () => fetchProjectTimeline(projectId!, filters, LIMIT, offset),
    enabled: !!projectId,
    staleTime: 30_000,
  });

  const entries = data?.entries ?? [];
  const total = data?.total ?? 0;

  // Resolve actor UUIDs to display names (OC-15)
  const { data: userList = [] } = useQuery<{ id: string; email: string; full_name: string }[]>({
    queryKey: ['users-search'],
    queryFn: () => apiGet('/v1/users/?limit=100&is_active=true'),
    staleTime: 60_000,
  });
  const userMap = useMemo(
    () => new Map(userList.map((u) => [u.id, u.full_name || u.email])),
    [userList],
  );

  const modules = useMemo(() => {
    const set = new Set<string>();
    entries.forEach((e) => e.module && set.add(e.module));
    return Array.from(set).sort();
  }, [entries]);

  const filtered = useMemo(() => {
    if (!search) return entries;
    const q = search.toLowerCase();
    return entries.filter(
      (e) =>
        e.action.toLowerCase().includes(q) ||
        (e.entity_type && e.entity_type.toLowerCase().includes(q)) ||
        (e.module && e.module.toLowerCase().includes(q)) ||
        (e.reason && e.reason.toLowerCase().includes(q)),
    );
  }, [entries, search]);

  // Activity stats from the current page
  const stats = useMemo(() => {
    const byAction: Record<string, number> = {};
    const byModule: Record<string, number> = {};
    for (const e of entries) {
      byAction[e.action] = (byAction[e.action] ?? 0) + 1;
      if (e.module) byModule[e.module] = (byModule[e.module] ?? 0) + 1;
    }
    const topActions = Object.entries(byAction).sort((a, b) => b[1] - a[1]).slice(0, 5);
    const topModules = Object.entries(byModule).sort((a, b) => b[1] - a[1]).slice(0, 5);
    return { topActions, topModules, total };
  }, [entries, total]);

  const applyFilters = useCallback(() => {
    setOffset(0);
    const f: TimelineFilters = {};
    if (moduleFilter) f.module = [moduleFilter];
    if (actionFilter) f.action = [actionFilter];
    if (sinceFilter) f.since = new Date(sinceFilter).toISOString();
    if (untilFilter) f.until = new Date(untilFilter + 'T23:59:59').toISOString();
    setFilters(f);
  }, [moduleFilter, actionFilter, sinceFilter, untilFilter]);

  const clearFilters = useCallback(() => {
    setModuleFilter('');
    setActionFilter('');
    setSinceFilter('');
    setUntilFilter('');
    setOffset(0);
    setFilters({});
  }, []);

  const hasActiveFilters = moduleFilter || actionFilter || sinceFilter || untilFilter;

  useEffect(() => { setOffset(0); }, [projectId]);

  const pageCount = Math.ceil(total / LIMIT);
  const currentPage = Math.floor(offset / LIMIT) + 1;

  const handleExportCsv = useCallback(() => {
    if (!filtered.length) return;
    const headers = ['Date', 'Action', 'Module', 'Entity Type', 'Entity ID', 'From Status', 'To Status', 'Reason'];
    const rows = filtered.map((e) => [
      e.created_at ? new Date(e.created_at).toISOString() : '',
      e.action, e.module ?? '', e.entity_type ?? '', e.entity_id ?? '',
      e.from_status ?? '', e.to_status ?? '', e.reason ?? '',
    ]);
    const csv = [headers, ...rows].map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `timeline-${projectId}-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [filtered, projectId]);

  if (!projectId) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-6">
        <PageHeader
          srTitle={t('timeline.title', { defaultValue: 'Project Timeline' })}
          subtitle={t('timeline.subtitle', {
            defaultValue: 'Activity feed across all modules for this project',
          })}
        />
        <EmptyState
          icon={<Activity className="h-12 w-12" />}
          title={t('timeline.no_project', { defaultValue: 'Select a project' })}
          description={t('timeline.no_project_desc', {
            defaultValue: 'Choose a project from the header to see its activity timeline.',
          })}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <PageHeader
        srTitle={t('timeline.title', { defaultValue: 'Project Timeline' })}
        subtitle={t('timeline.subtitle', {
          defaultValue: 'Activity feed across all modules for this project',
        })}
      />

      {/* Stats bar */}
      {!isLoading && entries.length > 0 && (
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-lg border border-gray-100 bg-white px-4 py-3 dark:border-gray-800 dark:bg-gray-900">
            <p className="text-2xs font-medium uppercase text-gray-500">{t('timeline.total_events', { defaultValue: 'Total Events' })}</p>
            <p className="mt-1 text-xl font-bold text-gray-900 dark:text-gray-100">{total}</p>
          </div>
          <div className="rounded-lg border border-gray-100 bg-white px-4 py-3 dark:border-gray-800 dark:bg-gray-900">
            <p className="text-2xs font-medium uppercase text-gray-500">{t('timeline.modules_active', { defaultValue: 'Modules Active' })}</p>
            <p className="mt-1 text-xl font-bold text-gray-900 dark:text-gray-100">{stats.topModules.length}</p>
          </div>
          <div className="col-span-2 rounded-lg border border-gray-100 bg-white px-4 py-3 dark:border-gray-800 dark:bg-gray-900">
            <p className="text-2xs font-medium uppercase text-gray-500 mb-1.5">{t('timeline.top_actions', { defaultValue: 'Top Actions' })}</p>
            <div className="flex flex-wrap gap-1.5">
              {stats.topActions.map(([action, count]) => (
                <span key={action} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-medium ${actionColor(action)}`}>
                  {formatAction(action)} <span className="opacity-60">{count}</span>
                </span>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Filter bar */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            type="text"
            placeholder={t('timeline.search', { defaultValue: 'Search actions, modules, entities...' })}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-200 bg-white py-2 ps-10 pe-4 text-sm
              focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500
              dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="absolute right-3 top-1/2 -translate-y-1/2"
              aria-label={t('common.clear_search', { defaultValue: 'Clear search' })}
            >
              <X className="h-4 w-4 text-gray-400 hover:text-gray-600" aria-hidden />
            </button>
          )}
        </div>

        <select
          value={moduleFilter}
          onChange={(e) => { setModuleFilter(e.target.value); setOffset(0); setFilters(e.target.value ? { ...filters, module: [e.target.value] } : { ...filters, module: undefined }); }}
          className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm
            dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
        >
          <option value="">{t('timeline.all_modules', { defaultValue: 'All modules' })}</option>
          {modules.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>

        <button
          onClick={() => setShowFilters(!showFilters)}
          className={`flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm transition-colors
            ${hasActiveFilters
              ? 'border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-700 dark:bg-blue-950 dark:text-blue-300'
              : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300'}`}
          aria-label={t('timeline.toggle_filters', { defaultValue: 'Toggle filters' })}
        >
          <Filter className="h-3.5 w-3.5" aria-hidden />
          {t('timeline.filters', { defaultValue: 'Filters' })}
          {hasActiveFilters && <span className="ml-1 rounded-full bg-blue-500 px-1.5 py-0.5 text-2xs text-white font-bold">!</span>}
        </button>

        <button
          onClick={handleExportCsv}
          disabled={!filtered.length}
          className="flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-600
            hover:border-gray-300 disabled:opacity-40 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300"
          aria-label={t('timeline.export_csv', { defaultValue: 'Export CSV' })}
        >
          <Download className="h-3.5 w-3.5" aria-hidden />
          CSV
        </button>
      </div>

      {/* Advanced filters panel */}
      {showFilters && (
        <div className="mb-4 rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-800/50">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <label className="mb-1 block text-2xs font-medium text-gray-500 uppercase">{t('timeline.action_type', { defaultValue: 'Action Type' })}</label>
              <select
                value={actionFilter}
                onChange={(e) => setActionFilter(e.target.value)}
                className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
              >
                <option value="">{t('timeline.all_actions', { defaultValue: 'All actions' })}</option>
                {ACTION_OPTIONS.map((a) => (
                  <option key={a} value={a}>{formatAction(a)}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-2xs font-medium text-gray-500 uppercase">{t('timeline.since', { defaultValue: 'From Date' })}</label>
              <input
                type="date"
                value={sinceFilter}
                onChange={(e) => setSinceFilter(e.target.value)}
                className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
              />
            </div>
            <div>
              <label className="mb-1 block text-2xs font-medium text-gray-500 uppercase">{t('timeline.until', { defaultValue: 'To Date' })}</label>
              <input
                type="date"
                value={untilFilter}
                onChange={(e) => setUntilFilter(e.target.value)}
                className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
              />
            </div>
            <div className="flex items-end gap-2">
              <button
                onClick={applyFilters}
                className="flex-1 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700"
              >
                {t('timeline.apply_filters', { defaultValue: 'Apply' })}
              </button>
              {hasActiveFilters && (
                <button
                  onClick={clearFilters}
                  className="rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-500 hover:bg-gray-100 dark:border-gray-700 dark:text-gray-400 dark:hover:bg-gray-800"
                >
                  {t('common.clear', { defaultValue: 'Clear' })}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Main content */}
      {isLoading && (
        <div className="py-16 text-center text-gray-500">
          <Clock className="mx-auto mb-2 h-6 w-6 animate-spin" />
          {t('common.loading', { defaultValue: 'Loading...' })}
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {t('timeline.load_error', { defaultValue: 'Could not load timeline' })}
        </div>
      )}

      {!isLoading && !error && filtered.length === 0 && (
        <EmptyState
          icon={<Activity className="h-12 w-12" />}
          title={t('timeline.empty', { defaultValue: 'No activity yet' })}
          description={t('timeline.empty_desc', {
            defaultValue: 'Activity will appear here as you work with this project.',
          })}
        />
      )}

      {!isLoading && filtered.length > 0 && (
        <div className="space-y-2">
          {filtered.map((entry) => (
            <TimelineRow
              key={entry.id}
              entry={entry}
              isSelected={selectedEntry?.id === entry.id}
              onSelect={() => setSelectedEntry(selectedEntry?.id === entry.id ? null : entry)}
              onNavigate={() => {
                const route = entityRoute(entry);
                if (route) navigate(route);
              }}
              userMap={userMap}
            />
          ))}
        </div>
      )}

      {/* Detail panel */}
      {selectedEntry && (
        <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50/50 p-4 dark:border-blue-900 dark:bg-blue-950/30">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
              {t('timeline.event_details', { defaultValue: 'Event Details' })}
            </h3>
            <button onClick={() => setSelectedEntry(null)} aria-label={t('common.close', { defaultValue: 'Close' })}>
              <X className="h-4 w-4 text-gray-400 hover:text-gray-600" aria-hidden />
            </button>
          </div>
          <div className="grid gap-2 text-sm sm:grid-cols-2">
            <div><span className="text-gray-500">{t('timeline.detail_action', { defaultValue: 'Action' })}:</span> <span className="font-medium">{formatAction(selectedEntry.action)}</span></div>
            <div><span className="text-gray-500">{t('timeline.detail_module', { defaultValue: 'Module' })}:</span> <span className="font-medium">{selectedEntry.module ?? '-'}</span></div>
            <div><span className="text-gray-500">{t('timeline.detail_entity_type', { defaultValue: 'Entity Type' })}:</span> <span className="font-medium">{selectedEntry.entity_type ?? '-'}</span></div>
            <div><span className="text-gray-500">{t('timeline.detail_entity_id', { defaultValue: 'Entity ID' })}:</span> <span className="font-mono text-xs">{selectedEntry.entity_id ?? '-'}</span></div>
            <div><span className="text-gray-500">{t('timeline.detail_timestamp', { defaultValue: 'Timestamp' })}:</span> <span className="font-medium">{fullDateTime(selectedEntry.created_at)}</span></div>
            <div><span className="text-gray-500">{t('timeline.detail_actor', { defaultValue: 'Actor' })}:</span> <span className="text-sm font-medium">{selectedEntry.actor_id ? (userMap.get(selectedEntry.actor_id) ?? selectedEntry.actor_id.slice(0, 8) + '...') : t('timeline.system', { defaultValue: 'System' })}</span></div>
            {selectedEntry.from_status && selectedEntry.to_status && (
              <div className="sm:col-span-2">
                <span className="text-gray-500">{t('timeline.detail_status_change', { defaultValue: 'Status Change' })}:</span>{' '}
                <span className="font-medium">{selectedEntry.from_status}</span>
                <ArrowRight className="inline mx-1 h-3 w-3 text-gray-400" />
                <span className="font-medium">{selectedEntry.to_status}</span>
              </div>
            )}
            {selectedEntry.reason && (
              <div className="sm:col-span-2"><span className="text-gray-500">{t('timeline.detail_reason', { defaultValue: 'Reason' })}:</span> <span className="font-medium">{selectedEntry.reason}</span></div>
            )}
            {selectedEntry.metadata && Object.keys(selectedEntry.metadata).length > 0 && (
              <div className="sm:col-span-2">
                <p className="mb-1 text-gray-500">{t('timeline.detail_metadata', { defaultValue: 'Metadata' })}:</p>
                <pre className="max-h-48 overflow-auto rounded bg-gray-100 p-2 text-xs text-gray-700 dark:bg-gray-800 dark:text-gray-300">
                  {JSON.stringify(selectedEntry.metadata, null, 2)}
                </pre>
              </div>
            )}
            {entityRoute(selectedEntry) && (
              <div className="sm:col-span-2">
                <button
                  onClick={() => { const r = entityRoute(selectedEntry); if (r) navigate(r); }}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
                >
                  <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                  {t('timeline.go_to_entity', { defaultValue: 'Go to Record' })}
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Pagination */}
      {total > LIMIT && (
        <div className="mt-4 flex items-center justify-between text-sm text-gray-500">
          <span>
            {t('timeline.showing', {
              defaultValue: '{{from}}-{{to}} of {{total}}',
              from: offset + 1,
              to: Math.min(offset + LIMIT, total),
              total,
            })}
          </span>
          <div className="flex gap-1">
            <button
              onClick={() => setOffset(Math.max(0, offset - LIMIT))}
              disabled={offset === 0}
              className="rounded p-1.5 hover:bg-gray-100 disabled:opacity-30 dark:hover:bg-gray-800"
              aria-label={t('common.previous_page', { defaultValue: 'Previous page' })}
            >
              <ChevronLeft className="h-4 w-4" aria-hidden />
            </button>
            <span className="px-2 py-1">{currentPage} / {pageCount}</span>
            <button
              onClick={() => setOffset(offset + LIMIT)}
              disabled={offset + LIMIT >= total}
              className="rounded p-1.5 hover:bg-gray-100 disabled:opacity-30 dark:hover:bg-gray-800"
              aria-label={t('common.next_page', { defaultValue: 'Next page' })}
            >
              <ChevronRight className="h-4 w-4" aria-hidden />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function TimelineRow({ entry, isSelected, onSelect, onNavigate, userMap }: {
  entry: TimelineEntry;
  isSelected: boolean;
  onSelect: () => void;
  onNavigate: () => void;
  userMap: Map<string, string>;
}) {
  const actorName = entry.actor_id ? userMap.get(entry.actor_id) : null;
  const route = entityRoute(entry);
  return (
    <div
      className={`flex items-start gap-3 rounded-lg border px-4 py-3
        transition-colors cursor-pointer
        ${isSelected
          ? 'border-blue-300 bg-blue-50 dark:border-blue-800 dark:bg-blue-950/30'
          : 'border-gray-100 bg-white hover:bg-gray-50 dark:border-gray-800 dark:bg-gray-900 dark:hover:bg-gray-800/50'}`}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(); } }}
    >
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-100 dark:bg-gray-800" title={actorName ?? undefined}>
        {entry.actor_id ? (
          <UserIcon className="h-4 w-4 text-gray-500" />
        ) : (
          <Activity className="h-4 w-4 text-gray-500" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          {actorName && (
            <span className="text-xs font-medium text-gray-700 dark:text-gray-300">{actorName}</span>
          )}
          <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${actionColor(entry.action)}`}>
            {formatAction(entry.action)}
          </span>
          {entry.module && (
            <Badge variant="blue" className="text-xs">{entry.module}</Badge>
          )}
          <span className="text-xs text-gray-500">{entry.entity_type}</span>
          {entry.from_status && entry.to_status && (
            <span className="flex items-center gap-1 text-xs text-gray-500">
              <span className="rounded bg-gray-100 px-1.5 py-0.5 dark:bg-gray-800">{entry.from_status}</span>
              <ArrowRight className="h-3 w-3" />
              <span className="rounded bg-gray-100 px-1.5 py-0.5 dark:bg-gray-800">{entry.to_status}</span>
            </span>
          )}
          {route && (
            <button
              onClick={(e) => { e.stopPropagation(); onNavigate(); }}
              className="text-blue-500 hover:text-blue-700"
              aria-label="Go to record"
            >
              <ExternalLink className="h-3 w-3" />
            </button>
          )}
        </div>
        {entry.reason && (
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">{entry.reason}</p>
        )}
      </div>
      <div className="shrink-0 text-right">
        <span className="text-xs text-gray-400" title={fullDateTime(entry.created_at)}>
          {relativeTime(entry.created_at)}
        </span>
      </div>
    </div>
  );
}

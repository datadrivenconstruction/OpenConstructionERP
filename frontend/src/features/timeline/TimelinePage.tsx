// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  Clock,
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

export function TimelinePage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const activeProjectId = useProjectContextStore((s: { activeProjectId: string | null }) => s.activeProjectId);
  const projectId = routeProjectId || activeProjectId;

  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState('');
  const [moduleFilter, setModuleFilter] = useState('');
  const [filters, setFilters] = useState<TimelineFilters>({});

  const { data, isLoading, error } = useQuery({
    queryKey: ['timeline', projectId, filters, offset],
    queryFn: () => fetchProjectTimeline(projectId!, filters, LIMIT, offset),
    enabled: !!projectId,
    staleTime: 30_000,
  });

  const entries = data?.entries ?? [];
  const total = data?.total ?? 0;

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

  const applyModuleFilter = useCallback(
    (mod: string) => {
      setModuleFilter(mod);
      setOffset(0);
      setFilters(mod ? { module: [mod] } : {});
    },
    [],
  );

  useEffect(() => { setOffset(0); }, [projectId]);

  const pageCount = Math.ceil(total / LIMIT);
  const currentPage = Math.floor(offset / LIMIT) + 1;

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

      {/* Filter bar */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <input
            type="text"
            placeholder={t('timeline.search', { defaultValue: 'Search actions, modules, entities...' })}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-200 bg-white py-2 pl-10 pr-4 text-sm
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
          onChange={(e) => applyModuleFilter(e.target.value)}
          className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm
            dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
        >
          <option value="">{t('timeline.all_modules', { defaultValue: 'All modules' })}</option>
          {modules.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>

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
            <TimelineRow key={entry.id} entry={entry} />
          ))}
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

function TimelineRow({ entry }: { entry: TimelineEntry }) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-gray-100 bg-white px-4 py-3
      transition-colors hover:bg-gray-50 dark:border-gray-800 dark:bg-gray-900 dark:hover:bg-gray-800/50">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-100 dark:bg-gray-800">
        {entry.actor_id ? (
          <UserIcon className="h-4 w-4 text-gray-500" />
        ) : (
          <Activity className="h-4 w-4 text-gray-500" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
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
        </div>
        {entry.reason && (
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">{entry.reason}</p>
        )}
      </div>
      <div className="shrink-0 text-right">
        <span className="text-xs text-gray-400" title={entry.created_at ?? ''}>
          {relativeTime(entry.created_at)}
        </span>
      </div>
    </div>
  );
}

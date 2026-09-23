// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Unified Issue Hub - one pane for everything open on a project.
//
// A defect, snag, non-conformance, clash or coordination topic can be raised
// in five different modules, each with its own list. This page unions them,
// read only, into a single KPI strip + filterable, sortable table so a team
// can see who owns what and what is overdue, then deep-link straight back to
// the owning module to act on any row.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Inbox,
  AlertTriangle,
  Flame,
  CircleDot,
  Filter,
  ArrowUpDown,
  Search,
  ArrowUpRight,
  RefreshCw,
  PenTool,
  ListChecks,
  AlertOctagon,
  Radar,
  MessageSquare,
  type LucideIcon,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  SkeletonTable,
  KpiBand,
  type KpiBandItem,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAllIssues, SOURCE_ORDER } from './useAllIssues';
import {
  isOverdue,
  type IssueSource,
  type IssuePriority,
  type IssueStatusBucket,
  type IssueSortKey,
  type UnifiedIssue,
} from './issueSources';
import { fmtList } from '@/shared/lib/formatters';

/* --- Constants + small helpers -------------------------------------------- */

interface Project {
  id: string;
  name: string;
}

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

const controlCls =
  'h-10 rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary ' +
  'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Show a short, readable token for an owner id (UUIDs get a #prefix stub). */
function assigneeLabel(token: string): string {
  return UUID_RE.test(token) ? `#${token.slice(0, 8)}` : token;
}

const SOURCE_META: Record<
  IssueSource,
  { icon: LucideIcon; labelKey: string; labelDefault: string; variant: BadgeVariant }
> = {
  punch: { icon: ListChecks, labelKey: 'issues.source_punch', labelDefault: 'Punch', variant: 'warning' },
  ncr: { icon: AlertOctagon, labelKey: 'issues.source_ncr', labelDefault: 'NCR', variant: 'error' },
  clash: { icon: Radar, labelKey: 'issues.source_clash', labelDefault: 'Clash', variant: 'blue' },
  markup: { icon: PenTool, labelKey: 'issues.source_markup', labelDefault: 'Mark-up', variant: 'blue' },
  bcf: { icon: MessageSquare, labelKey: 'issues.source_bcf', labelDefault: 'BCF', variant: 'neutral' },
};

const PRIORITY_BADGE: Record<IssuePriority, BadgeVariant> = {
  critical: 'error',
  high: 'warning',
  medium: 'blue',
  low: 'neutral',
  none: 'neutral',
};

const STATUS_BADGE: Record<IssueStatusBucket, BadgeVariant> = {
  open: 'error',
  in_progress: 'warning',
  resolved: 'blue',
  closed: 'neutral',
};

const PRIORITY_LABEL_DEFAULT: Record<IssuePriority, string> = {
  critical: 'Critical',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
  none: '-',
};

const STATUS_LABEL_DEFAULT: Record<IssueStatusBucket, string> = {
  open: 'Open',
  in_progress: 'In progress',
  resolved: 'Resolved',
  closed: 'Closed',
};

const UNASSIGNED = '__unassigned__';

/* --- Page ----------------------------------------------------------------- */

export function IssuesHubPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
    staleTime: 5 * 60_000,
  });

  const projectId = activeProjectId || projects[0]?.id || '';
  const breadcrumbProjectName = activeProjectId
    ? projects.find((p) => p.id === activeProjectId)?.name
    : undefined;

  // Filters + sort
  const [sortKey, setSortKey] = useState<IssueSortKey>('priority');
  const [filterSource, setFilterSource] = useState<IssueSource | 'all'>('all');
  const [filterStatus, setFilterStatus] = useState<IssueStatusBucket | 'all'>('all');
  const [filterAssignee, setFilterAssignee] = useState<string>('all');
  const [filterPriority, setFilterPriority] = useState<IssuePriority | 'all'>('all');
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [search, setSearch] = useState('');

  const { issues, bySource, sources, warnings, isLoading, isError, refetch } = useAllIssues(
    projectId,
    sortKey,
  );

  // KPI metrics reflect the whole project, not the filtered view.
  const metrics = useMemo(() => {
    const now = new Date();
    let overdue = 0;
    let critical = 0;
    let high = 0;
    let medium = 0;
    let low = 0;
    for (const i of issues) {
      if (isOverdue(i, now)) overdue += 1;
      if (i.priority === 'critical') critical += 1;
      else if (i.priority === 'high') high += 1;
      else if (i.priority === 'medium') medium += 1;
      else if (i.priority === 'low') low += 1;
    }
    return { total: issues.length, overdue, critical, high, medium, low };
  }, [issues]);

  const assigneeOptions = useMemo(() => {
    const set = new Set<string>();
    for (const i of issues) if (i.assignee) set.add(i.assignee);
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [issues]);

  const filtered = useMemo(() => {
    const now = new Date();
    const q = search.trim().toLowerCase();
    return issues.filter((i) => {
      if (filterSource !== 'all' && i.source !== filterSource) return false;
      if (filterStatus !== 'all' && i.status !== filterStatus) return false;
      if (filterPriority !== 'all' && i.priority !== filterPriority) return false;
      if (filterAssignee !== 'all') {
        if (filterAssignee === UNASSIGNED) {
          if (i.assignee) return false;
        } else if (i.assignee !== filterAssignee) {
          return false;
        }
      }
      if (overdueOnly && !isOverdue(i, now)) return false;
      if (q) {
        const inTitle = i.title.toLowerCase().includes(q);
        const inAssignee = (i.assignee ?? '').toLowerCase().includes(q);
        if (!inTitle && !inAssignee) return false;
      }
      return true;
    });
  }, [issues, filterSource, filterStatus, filterPriority, filterAssignee, overdueOnly, search]);

  const hasActiveFilters =
    filterSource !== 'all' ||
    filterStatus !== 'all' ||
    filterPriority !== 'all' ||
    filterAssignee !== 'all' ||
    overdueOnly ||
    search.trim().length > 0;

  const clearFilters = () => {
    setFilterSource('all');
    setFilterStatus('all');
    setFilterPriority('all');
    setFilterAssignee('all');
    setOverdueOnly(false);
    setSearch('');
  };

  const showPriority = (p: IssuePriority) => {
    setFilterPriority((prev) => (prev === p ? 'all' : p));
    setOverdueOnly(false);
  };

  const kpiItems: KpiBandItem[] = [
    {
      key: 'total',
      label: t('issues.kpi_total', { defaultValue: 'Open issues' }),
      value: metrics.total,
      sub: t('issues.kpi_total_sub', { defaultValue: 'across all sources' }),
      icon: Inbox,
      tone: metrics.total > 0 ? 'blue' : 'success',
      tintValue: metrics.total > 0,
      onClick: clearFilters,
      ariaLabel: t('issues.kpi_total_aria', { defaultValue: 'Show all open issues' }),
    },
    {
      key: 'overdue',
      label: t('issues.kpi_overdue', { defaultValue: 'Overdue' }),
      value: metrics.overdue,
      sub: t('issues.kpi_overdue_sub', { defaultValue: 'past due date' }),
      icon: AlertTriangle,
      tone: metrics.overdue > 0 ? 'danger' : 'default',
      tintValue: metrics.overdue > 0,
      onClick: () => {
        setOverdueOnly(true);
        setFilterPriority('all');
      },
      ariaLabel: t('issues.kpi_overdue_aria', { defaultValue: 'Filter to overdue issues' }),
    },
    {
      key: 'critical',
      label: t('issues.priority_critical', { defaultValue: 'Critical' }),
      value: metrics.critical,
      icon: Flame,
      tone: metrics.critical > 0 ? 'danger' : 'default',
      tintValue: metrics.critical > 0,
      onClick: () => showPriority('critical'),
      ariaLabel: t('issues.kpi_critical_aria', { defaultValue: 'Filter to critical issues' }),
    },
    {
      key: 'high',
      label: t('issues.priority_high', { defaultValue: 'High' }),
      value: metrics.high,
      icon: AlertTriangle,
      tone: metrics.high > 0 ? 'warning' : 'default',
      tintValue: metrics.high > 0,
      onClick: () => showPriority('high'),
      ariaLabel: t('issues.kpi_high_aria', { defaultValue: 'Filter to high priority issues' }),
    },
    {
      key: 'medium',
      label: t('issues.priority_medium', { defaultValue: 'Medium' }),
      value: metrics.medium,
      icon: CircleDot,
      tone: 'blue',
      tintValue: metrics.medium > 0,
      onClick: () => showPriority('medium'),
      ariaLabel: t('issues.kpi_medium_aria', { defaultValue: 'Filter to medium priority issues' }),
    },
    {
      key: 'low',
      label: t('issues.priority_low', { defaultValue: 'Low' }),
      value: metrics.low,
      icon: CircleDot,
      tone: 'default',
      onClick: () => showPriority('low'),
      ariaLabel: t('issues.kpi_low_aria', { defaultValue: 'Filter to low priority issues' }),
    },
  ];

  return (
    <div className="animate-fade-in space-y-5">
      <Breadcrumb
        items={[
          ...(breadcrumbProjectName && activeProjectId
            ? [{ label: breadcrumbProjectName, to: `/projects/${activeProjectId}` }]
            : []),
          { label: t('issues.title', { defaultValue: 'Issue Hub' }) },
        ]}
      />

      <PageHeader
        srTitle={t('issues.title', { defaultValue: 'Issue Hub' })}
        subtitle={t('issues.subtitle', {
          defaultValue:
            'One list of everything open on the project - punch items, NCRs, clashes, mark-ups and coordination topics - so nothing falls between the cracks.',
        })}
        actions={
          <Button
            variant="secondary"
            size="sm"
            onClick={() => refetch()}
            disabled={!projectId}
            icon={<RefreshCw size={14} />}
          >
            {t('common.refresh', { defaultValue: 'Refresh' })}
          </Button>
        }
      />

      {!projectId ? (
        <RequiresProject
          emptyHint={t('issues.select_project', {
            defaultValue: 'Open a project first to see its open issues.',
          })}
        >
          {null}
        </RequiresProject>
      ) : (
        <>
          <KpiBand items={kpiItems} columns={6} />

          {/* Source chips - counts per module, click to filter to one source. */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setFilterSource('all')}
              className={clsx(
                'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
                filterSource === 'all'
                  ? 'border-oe-blue bg-oe-blue/10 text-oe-blue-text'
                  : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary',
              )}
              aria-pressed={filterSource === 'all'}
            >
              {t('issues.source_all', { defaultValue: 'All sources' })}
              <span className="tabular-nums font-semibold">{issues.length}</span>
            </button>
            {SOURCE_ORDER.map((source) => {
              const state = sources.find((s) => s.source === source);
              // Hide a source that is disabled and empty (e.g. BCF not wired yet).
              if (state && state.status === 'disabled') return null;
              const meta = SOURCE_META[source];
              const Icon = meta.icon;
              const count = bySource[source] ?? 0;
              const isErr = state?.status === 'error';
              const active = filterSource === source;
              return (
                <button
                  key={source}
                  type="button"
                  onClick={() => setFilterSource(active ? 'all' : source)}
                  className={clsx(
                    'inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
                    active
                      ? 'border-oe-blue bg-oe-blue/10 text-oe-blue-text'
                      : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary',
                  )}
                  aria-pressed={active}
                  title={
                    isErr
                      ? t('issues.source_failed', { defaultValue: 'This source could not be loaded' })
                      : undefined
                  }
                >
                  <Icon size={13} className="shrink-0" />
                  {t(meta.labelKey, { defaultValue: meta.labelDefault })}
                  {isErr ? (
                    <AlertTriangle size={12} className="text-semantic-error shrink-0" />
                  ) : (
                    <span className="tabular-nums font-semibold">{count}</span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Partial-failure banner - some sources loaded, others did not. */}
          {warnings.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
              <AlertTriangle size={14} className="shrink-0" />
              <span>
                {t('issues.partial_warning', {
                  defaultValue:
                    'Some sources could not be loaded, so this list may be incomplete: {{sources}}.',
                  sources: fmtList(warnings
                    .map((w) =>
                      t(SOURCE_META[w.source].labelKey, {
                        defaultValue: SOURCE_META[w.source].labelDefault,
                      }),
                    )),
                })}
              </span>
              <Button variant="ghost" size="sm" onClick={() => refetch()} className="ml-auto">
                <RefreshCw size={12} className="mr-1 shrink-0" />
                {t('common.retry', { defaultValue: 'Retry' })}
              </Button>
            </div>
          )}

          {/* Toolbar: search + filters + sort */}
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="relative max-w-sm flex-1">
              <Search
                size={16}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
              />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('issues.search', { defaultValue: 'Search title or owner...' })}
                aria-label={t('issues.search', { defaultValue: 'Search title or owner...' })}
                className={controlCls + ' w-full pl-9'}
              />
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Filter size={14} className="text-content-tertiary" />

              <select
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value as IssueStatusBucket | 'all')}
                aria-label={t('issues.filter_status', { defaultValue: 'Status' })}
                className={controlCls}
              >
                <option value="all">{t('issues.all_statuses', { defaultValue: 'All statuses' })}</option>
                <option value="open">{t('issues.status_open', { defaultValue: 'Open' })}</option>
                <option value="in_progress">
                  {t('issues.status_in_progress', { defaultValue: 'In progress' })}
                </option>
                <option value="resolved">
                  {t('issues.status_resolved', { defaultValue: 'Resolved' })}
                </option>
              </select>

              <select
                value={filterAssignee}
                onChange={(e) => setFilterAssignee(e.target.value)}
                aria-label={t('issues.filter_assignee', { defaultValue: 'Assignee' })}
                className={controlCls + ' max-w-[180px]'}
              >
                <option value="all">{t('issues.all_assignees', { defaultValue: 'All owners' })}</option>
                <option value={UNASSIGNED}>
                  {t('issues.unassigned', { defaultValue: 'Unassigned' })}
                </option>
                {assigneeOptions.map((a) => (
                  <option key={a} value={a}>
                    {assigneeLabel(a)}
                  </option>
                ))}
              </select>

              <label className="inline-flex items-center gap-1.5 text-xs text-content-secondary">
                <input
                  type="checkbox"
                  checked={overdueOnly}
                  onChange={(e) => setOverdueOnly(e.target.checked)}
                  className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue/30"
                />
                {t('issues.overdue_only', { defaultValue: 'Overdue only' })}
              </label>

              <div className="flex items-center gap-1">
                <ArrowUpDown size={14} className="text-content-tertiary" />
                <select
                  value={sortKey}
                  onChange={(e) => setSortKey(e.target.value as IssueSortKey)}
                  aria-label={t('issues.sort_by', { defaultValue: 'Sort by' })}
                  className={controlCls}
                >
                  <option value="priority">
                    {t('issues.sort_priority', { defaultValue: 'Priority' })}
                  </option>
                  <option value="due">{t('issues.sort_due', { defaultValue: 'Due date' })}</option>
                  <option value="created">
                    {t('issues.sort_created', { defaultValue: 'Newest' })}
                  </option>
                </select>
              </div>

              {hasActiveFilters && (
                <Button variant="ghost" size="sm" onClick={clearFilters}>
                  {t('issues.clear_filters', { defaultValue: 'Clear' })}
                </Button>
              )}
            </div>
          </div>

          {/* Body */}
          {isLoading ? (
            <SkeletonTable rows={6} columns={6} />
          ) : isError ? (
            <EmptyState
              icon={<AlertTriangle size={28} strokeWidth={1.5} />}
              title={t('issues.error_title', { defaultValue: 'Could not load issues' })}
              description={t('issues.error_desc', {
                defaultValue: 'None of the issue sources responded. Check your connection and try again.',
              })}
              action={{
                label: t('common.retry', { defaultValue: 'Retry' }),
                onClick: () => refetch(),
              }}
            />
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={<Inbox size={28} strokeWidth={1.5} />}
              title={
                hasActiveFilters
                  ? t('issues.empty_filtered_title', { defaultValue: 'No issues match these filters' })
                  : t('issues.empty_title', { defaultValue: 'Nothing open right now' })
              }
              description={
                hasActiveFilters
                  ? t('issues.empty_filtered_desc', {
                      defaultValue: 'Try clearing a filter to widen the list.',
                    })
                  : t('issues.empty_desc', {
                      defaultValue:
                        'Open punch items, NCRs, clashes and mark-up call-outs will appear here as they are raised.',
                    })
              }
              action={
                hasActiveFilters
                  ? {
                      label: t('issues.clear_filters', { defaultValue: 'Clear filters' }),
                      onClick: clearFilters,
                    }
                  : undefined
              }
            />
          ) : (
            <>
              <p className="text-sm text-content-tertiary">
                {t('issues.showing_count', {
                  defaultValue: 'Showing {{count}} of {{total}} open issues',
                  count: filtered.length,
                  total: issues.length,
                })}
              </p>
              <Card padding="none" className="overflow-x-auto">
                {/* Header */}
                <div className="flex items-center gap-3 border-b border-border-light bg-surface-secondary/30 px-4 py-2.5 text-2xs font-medium uppercase tracking-wider text-content-tertiary min-w-[760px]">
                  <span className="w-24 shrink-0">{t('issues.col_source', { defaultValue: 'Source' })}</span>
                  <span className="flex-1 min-w-0">{t('issues.col_title', { defaultValue: 'Title' })}</span>
                  <span className="w-24 shrink-0 text-center">
                    {t('issues.col_priority', { defaultValue: 'Priority' })}
                  </span>
                  <span className="w-28 shrink-0 text-center">
                    {t('issues.col_status', { defaultValue: 'Status' })}
                  </span>
                  <span className="hidden w-32 shrink-0 md:block">
                    {t('issues.col_assignee', { defaultValue: 'Owner' })}
                  </span>
                  <span className="w-28 shrink-0 text-right">
                    {t('issues.col_due', { defaultValue: 'Due' })}
                  </span>
                  <span className="w-6 shrink-0" />
                </div>

                {filtered.map((issue) => (
                  <IssueRow key={issue.id} issue={issue} onOpen={() => navigate(issue.deepLink)} />
                ))}
              </Card>
            </>
          )}
        </>
      )}
    </div>
  );
}

/* --- Row ------------------------------------------------------------------ */

function IssueRow({ issue, onOpen }: { issue: UnifiedIssue; onOpen: () => void }) {
  const { t } = useTranslation();
  const meta = SOURCE_META[issue.source];
  const SourceIcon = meta.icon;
  const overdue = isOverdue(issue);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onOpen();
        }
      }}
      title={t('issues.open_in_module', { defaultValue: 'Open in its module' })}
      className={clsx(
        'flex cursor-pointer items-center gap-3 border-b border-border-light px-4 py-3 text-sm transition-colors last:border-b-0 min-w-[760px]',
        'hover:bg-surface-secondary/50 focus:outline-none focus-visible:bg-surface-secondary/60',
        overdue && 'bg-red-50/40 dark:bg-red-950/15',
      )}
    >
      {/* Source */}
      <span className="w-24 shrink-0">
        <Badge variant={meta.variant} size="sm">
          <SourceIcon size={11} className="mr-1 shrink-0" />
          {t(meta.labelKey, { defaultValue: meta.labelDefault })}
        </Badge>
      </span>

      {/* Title */}
      <span className="min-w-0 flex-1 truncate text-content-primary" title={issue.title}>
        {issue.title}
      </span>

      {/* Priority */}
      <span className="w-24 shrink-0 text-center">
        {issue.priority === 'none' ? (
          <span className="text-content-quaternary">-</span>
        ) : (
          <Badge variant={PRIORITY_BADGE[issue.priority]} size="sm">
            {t(`issues.priority_${issue.priority}`, {
              defaultValue: PRIORITY_LABEL_DEFAULT[issue.priority],
            })}
          </Badge>
        )}
      </span>

      {/* Status */}
      <span className="w-28 shrink-0 text-center">
        <Badge variant={STATUS_BADGE[issue.status]} size="sm">
          {t(`issues.status_${issue.status}`, {
            defaultValue: STATUS_LABEL_DEFAULT[issue.status],
          })}
        </Badge>
      </span>

      {/* Owner */}
      <span className="hidden w-32 shrink-0 truncate text-content-secondary md:block">
        {issue.assignee ? (
          assigneeLabel(issue.assignee)
        ) : (
          <span className="text-content-quaternary">
            {t('issues.unassigned', { defaultValue: 'Unassigned' })}
          </span>
        )}
      </span>

      {/* Due */}
      <span
        className={clsx(
          'w-28 shrink-0 text-right tabular-nums',
          overdue ? 'font-medium text-semantic-error' : 'text-content-tertiary',
        )}
      >
        {issue.dueDate ? (
          <span className="inline-flex items-center justify-end gap-1">
            {overdue && <AlertTriangle size={11} className="shrink-0" />}
            <DateDisplay value={issue.dueDate} />
          </span>
        ) : (
          <span className="text-content-quaternary">-</span>
        )}
      </span>

      {/* Open affordance */}
      <span className="w-6 shrink-0 text-content-quaternary">
        <ArrowUpRight size={15} />
      </span>
    </div>
  );
}

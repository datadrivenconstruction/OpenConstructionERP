// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * InboxPage - full-page unified approvals/alerts inbox.
 *
 * Linked from the sidebar (Overview group) and the dashboard Inbox widget's
 * "View all". Aggregates the caller's pending approvals (file-approval +
 * change-order approval steps) and unread alerts via
 * ``GET /api/v1/dashboard/inbox/`` - one IDOR-scoped list.
 *
 * Beyond the widget it clones, the page adds two things that make it a real
 * triage surface: a short "what this is / how it fits" intro that links out to
 * the modules approvals and alerts originate from, and a client-side segmented
 * filter (All / Approvals / Alerts, plus project and severity) driven entirely
 * off the list already fetched - no extra endpoint. The list itself is rendered
 * by :mod:`InboxPanel`, which the page feeds the active filter.
 */
import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Bell, ClipboardCheck, Inbox as InboxIcon, Network, RefreshCw } from 'lucide-react';
import { Button, Card } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { SaveDefaultFilter } from '@/shared/ui/SaveDefaultFilter';
import { initialFilter } from '@/shared/lib/defaultFilters';
import { InboxPanel } from './InboxPanel';
import { useInboxQuery } from './useInbox';
import { SegmentedControl, type SegmentOption } from './SegmentedControl';
import {
  ALL_INBOX_FILTER,
  countApprovals,
  distinctInboxProjects,
  distinctInboxSeverities,
  filterInboxItems,
  isInboxFiltered,
  type InboxFilter,
  type InboxKindFilter,
  type InboxSeverityFilter,
} from './inboxUtils';

/** Cap requested for the full page (shared cache key with the counts below). */
const LIMIT = 100;

const SELECT_CLS =
  'rounded-lg border border-border-light bg-surface-primary px-2.5 py-1.5 text-xs ' +
  'text-content-secondary focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30';

/** A compact inline link to a sibling module (keeps the intro copy readable). */
function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * Plain-language "what this is / how it fits" block. States where inbox items
 * come from (approval steps + alerts) and links out to the real modules, so the
 * two-surfaces confusion (inbox vs notifications) is resolved in one line. Every
 * target route is confirmed to exist in App.tsx.
 */
function InboxIntro() {
  const { t } = useTranslation();
  return (
    <Card padding="md">
      <h2 className="flex items-center gap-1.5 text-sm font-semibold text-content-primary">
        <Network size={15} className="text-oe-blue" />
        {t('inbox.intro_title', { defaultValue: 'What the inbox is' })}
      </h2>
      <p className="mt-1 text-xs leading-relaxed text-content-tertiary">
        {t('inbox.intro_body', {
          defaultValue:
            'One triage list of everything waiting on you: pending approvals (file and change-order sign-offs) plus unread alerts, aggregated across every project you can access. Act on an item at its source and it clears from here.',
        })}
      </p>
      <div className="mt-3 flex flex-col gap-1.5 border-t border-border-light pt-3 text-2xs text-content-tertiary sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-1">
        <span>
          <span className="font-medium text-content-secondary">
            {t('inbox.intro_approvals_from', { defaultValue: 'Approvals come from:' })}
          </span>{' '}
          <ModLink to="/changeorders">
            {t('inbox.mod_change_orders', { defaultValue: 'Change Orders' })}
          </ModLink>{' '}
          ·{' '}
          <ModLink to="/files">{t('inbox.mod_files', { defaultValue: 'Project Files' })}</ModLink>
        </span>
        <span>
          <span className="font-medium text-content-secondary">
            {t('inbox.intro_related', { defaultValue: 'Related:' })}
          </span>{' '}
          <ModLink to="/notifications">
            {t('inbox.mod_notifications', { defaultValue: 'Notifications' })}
          </ModLink>{' '}
          <span>
            {t('inbox.intro_notifications_diff', {
              defaultValue:
                '- the full alert history; the inbox shows only what still needs action.',
            })}
          </span>
        </span>
      </div>
    </Card>
  );
}

export function InboxPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<InboxFilter>(() => {
    const saved = initialFilter('inbox', { kind: 'all', severity: 'all' });
    return {
      ...ALL_INBOX_FILTER,
      kind: ['approval', 'alert'].includes(saved.kind) ? (saved.kind as InboxKindFilter) : 'all',
      severity: ['critical', 'warning', 'info'].includes(saved.severity)
        ? (saved.severity as InboxSeverityFilter)
        : 'all',
    };
  });

  // Same query the panel reads (deduped by React Query on the ['inbox', LIMIT]
  // key): the page uses the raw items to build the filter controls + counts.
  const { data, isLoading, isError, isFetching } = useInboxQuery(LIMIT);
  const rawItems = useMemo(() => data?.items ?? [], [data?.items]);

  const handleRefresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['inbox'] });
  }, [queryClient]);

  const projects = useMemo(() => distinctInboxProjects(rawItems), [rawItems]);
  const severities = useMemo(() => distinctInboxSeverities(rawItems), [rawItems]);

  // Kind-segment counts reflect the OTHER active axes (project + severity), so
  // each segment's number equals exactly the list you get by clicking it.
  const kindScoped = useMemo(
    () => filterInboxItems(rawItems, { ...filter, kind: 'all' }),
    [rawItems, filter],
  );
  const approvals = countApprovals(kindScoped);
  const alerts = kindScoped.length - approvals;

  const kindOptions: SegmentOption<InboxKindFilter>[] = [
    {
      value: 'all',
      label: t('inbox.filter_all', { defaultValue: 'All' }),
      count: kindScoped.length,
      icon: <InboxIcon size={13} aria-hidden />,
    },
    {
      value: 'approval',
      label: t('inbox.filter_approvals', { defaultValue: 'Approvals' }),
      count: approvals,
      icon: <ClipboardCheck size={13} aria-hidden />,
    },
    {
      value: 'alert',
      label: t('inbox.filter_alerts', { defaultValue: 'Alerts' }),
      count: alerts,
      icon: <Bell size={13} aria-hidden />,
    },
  ];

  const severityLabel = (sev: InboxSeverityFilter): string => {
    switch (sev) {
      case 'critical':
        return t('inbox.sev_critical', { defaultValue: 'Critical' });
      case 'warning':
        return t('inbox.sev_warning', { defaultValue: 'Warning' });
      case 'info':
        return t('inbox.sev_info', { defaultValue: 'Info' });
      default:
        return t('inbox.filter_all_severities', { defaultValue: 'All severities' });
    }
  };

  const showControls = !isLoading && !isError && rawItems.length > 0;
  const filtered = isInboxFiltered(filter);

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        srTitle={t('inbox.title', { defaultValue: 'Inbox' })}
        subtitle={t('inbox.page_subtitle', {
          defaultValue:
            'Inbox is one triage list of everything waiting on you - pending approvals (file and change-order sign-offs) plus unread alerts - aggregated across every project you can access.',
        })}
        actions={
          <Button
            variant="secondary"
            size="sm"
            icon={<RefreshCw size={14} className={isFetching ? 'animate-spin' : undefined} />}
            onClick={handleRefresh}
            disabled={isFetching}
          >
            {t('common.refresh', { defaultValue: 'Refresh' })}
          </Button>
        }
      />

      <InboxIntro />

      {showControls && (
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
          <SegmentedControl
            ariaLabel={t('inbox.filter_kind_label', { defaultValue: 'Filter by type' })}
            options={kindOptions}
            value={filter.kind}
            onChange={(kind) => setFilter((f) => ({ ...f, kind }))}
            data-testid="inbox-filter-kind"
          />
          <div className="flex flex-wrap items-center gap-2">
            {projects.length > 1 && (
              <select
                className={SELECT_CLS}
                value={filter.projectId}
                onChange={(e) => setFilter((f) => ({ ...f, projectId: e.target.value }))}
                aria-label={t('inbox.filter_project_label', { defaultValue: 'Filter by project' })}
                data-testid="inbox-filter-project"
              >
                <option value="all">
                  {t('inbox.filter_all_projects', { defaultValue: 'All projects' })}
                </option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            )}
            {severities.length > 1 && (
              <select
                className={SELECT_CLS}
                value={filter.severity}
                onChange={(e) =>
                  setFilter((f) => ({ ...f, severity: e.target.value as InboxSeverityFilter }))
                }
                aria-label={t('inbox.filter_severity_label', {
                  defaultValue: 'Filter by severity',
                })}
                data-testid="inbox-filter-severity"
              >
                <option value="all">{severityLabel('all')}</option>
                {severities.map((s) => (
                  <option key={s} value={s}>
                    {severityLabel(s)}
                  </option>
                ))}
              </select>
            )}
            <SaveDefaultFilter
              page="inbox"
              current={{ kind: filter.kind, severity: filter.severity }}
              neutral={{ kind: 'all', severity: 'all' }}
            />
            {filtered && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setFilter(ALL_INBOX_FILTER)}
                data-testid="inbox-filter-clear"
              >
                {t('inbox.filter_clear', { defaultValue: 'Clear filters' })}
              </Button>
            )}
          </div>
        </div>
      )}

      <InboxPanel limit={LIMIT} showHeader={false} filter={filter} />
    </div>
  );
}

export default InboxPage;

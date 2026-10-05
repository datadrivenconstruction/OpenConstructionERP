// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * InboxPanel - the unified approvals/alerts list.
 *
 * Renders the caller's pending approvals + unread alerts (aggregated by
 * ``GET /api/v1/dashboard/inbox/``) as one chronologically-sorted, clickable
 * list. Reused in two places:
 *   - as a dashboard widget (``compact``, small ``limit``), and
 *   - as the body of the full ``/inbox`` page (``limit`` larger, header off
 *     because the page supplies its own).
 *
 * Each row links to the originating item via its ``action_url``; an alert
 * carries an i18n ``title_key`` we render with its ``body_context``.
 *
 * Rows can also be acted on. Acknowledging keeps the row and marks it seen, so
 * a long list can be worked through without anything vanishing; dismissing
 * takes it off the list and offers an undo. Both are per-user triage state -
 * dismissing an approval never decides it, and the toast says so.
 */
import { useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  ArrowRight,
  Bell,
  Check,
  CheckSquare,
  ClipboardCheck,
  Filter,
  Info,
  Inbox as InboxIcon,
  Loader2,
  Undo2,
  X,
  XCircle,
} from 'lucide-react';
import clsx from 'clsx';
import { Badge, Card, CardHeader } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  acknowledgeInboxItem,
  dismissInboxItem,
  restoreInboxItem,
  type InboxItem,
  type InboxSeverity,
  type InboxState,
} from './api';
import {
  countApprovals,
  filterInboxItems,
  formatTimeAgo,
  normalizeSeverity,
  resolveTitle,
  sortInboxItems,
  type InboxFilter,
} from './inboxUtils';
import { normalizeActionUrl } from '@/shared/lib/notificationActionUrl';
import { INBOX_QUERY_ROOT, useInboxQuery } from './useInbox';

export interface InboxPanelProps {
  /** Max rows requested from the backend. Default 8 (a compact widget). */
  limit?: number;
  /** Render the card chrome + header. Default true. Pages pass false. */
  showHeader?: boolean;
  /** Tighten spacing for the dashboard widget. */
  compact?: boolean;
  /**
   * Optional client-side triage filter (kind / project / severity). Applied to
   * the already-fetched list before rendering; when omitted the full list shows
   * (the dashboard widget passes nothing). No extra request is made.
   */
  filter?: InboxFilter;
}

// Severity → theme-aware semantic design tokens (the app-wide traffic-light
// system). Each text/bg pair is WCAG-AA contrast-tuned for BOTH light and dark
// themes in index.css (--oe-*-bg), so no hard-coded dark: variants are needed.
const SEVERITY_STYLE: Record<
  InboxSeverity,
  { color: string; bg: string }
> = {
  critical: { color: 'text-semantic-error', bg: 'bg-semantic-error-bg' },
  warning: { color: 'text-semantic-warning', bg: 'bg-semantic-warning-bg' },
  info: { color: 'text-semantic-info', bg: 'bg-semantic-info-bg' },
};

function severityIcon(severity: InboxSeverity) {
  if (severity === 'critical') return XCircle;
  if (severity === 'warning') return AlertTriangle;
  return Info;
}

function kindIcon(item: InboxItem) {
  if (item.kind === 'approval') {
    return item.source === 'change_order' ? ClipboardCheck : CheckSquare;
  }
  return Bell;
}

/** Shared styling for the small icon buttons at the end of a row. */
const ROW_ACTION_CLASS =
  'shrink-0 rounded-md p-1 text-content-quaternary transition-colors hover:bg-surface-tertiary ' +
  'hover:text-content-primary focus-visible:outline-none focus-visible:ring-2 ' +
  'focus-visible:ring-oe-blue/40 disabled:pointer-events-none disabled:opacity-40';

function InboxRow({ item }: { item: InboxItem }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const sev = normalizeSeverity(item.severity);
  const sevStyle = SEVERITY_STYLE[sev];
  const KindIcon = kindIcon(item);
  const SevIcon = severityIcon(sev);

  const ctx = useMemo(
    () =>
      item.body_context && typeof item.body_context === 'object'
        ? (item.body_context as Record<string, unknown>)
        : {},
    [item.body_context],
  );

  const titleSpec = resolveTitle(item);
  const title = t(titleSpec.key, { defaultValue: titleSpec.defaultValue, ...ctx });
  const timeAgo = formatTimeAgo(item.created_at, t);

  const onClick = useCallback(() => {
    if (item.action_url) navigate(normalizeActionUrl(item.action_url));
  }, [item.action_url, navigate]);

  // Both the dashboard widget and the /inbox page hold an ['inbox', limit]
  // entry; a prefix invalidation is what keeps them agreeing after an action.
  const refreshInbox = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: [INBOX_QUERY_ROOT] });
  }, [queryClient]);

  // Undo runs from a toast, by which point this row has already left the list
  // and unmounted, so it cannot go through the row's own mutation. The query
  // client outlives the row, so the refresh still lands.
  const undoDismiss = useCallback(() => {
    restoreInboxItem(item.id)
      .then(refreshInbox)
      .catch((error: unknown) => {
        addToast({
          type: 'error',
          title: t('inbox.restore_failed', { defaultValue: 'Could not put that back' }),
          message: getErrorMessage(error),
        });
      });
  }, [item.id, refreshInbox, addToast, t]);

  const action = useMutation({
    mutationFn: (next: InboxState) => {
      if (next === null) return restoreInboxItem(item.id);
      if (next === 'dismissed') return dismissInboxItem(item.id);
      return acknowledgeInboxItem(item.id);
    },
    onSuccess: (_data, next) => {
      refreshInbox();
      if (next !== 'dismissed') return;
      addToast(
        {
          type: 'info',
          title: t('inbox.dismissed_toast', { defaultValue: 'Removed from your inbox' }),
          // An approval leaves the list without being decided. Saying so here
          // is the whole reason dismissing an approval is allowed at all.
          message:
            item.kind === 'approval'
              ? t('inbox.dismissed_approval_note', {
                  defaultValue:
                    'The approval is still pending a decision in the module that owns it.',
                })
              : undefined,
          action: { label: t('common.undo', { defaultValue: 'Undo' }), onClick: undoDismiss },
        },
        { duration: 8000 },
      );
    },
  });

  const acknowledged = item.acknowledged === true;
  const clickable = Boolean(item.action_url);

  const rowBody = (
    <>
      <span
        className={clsx(
          'shrink-0 h-7 w-7 rounded-md flex items-center justify-center',
          sevStyle.bg,
        )}
      >
        <KindIcon size={14} className={sevStyle.color} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <p className="min-w-0 flex-1 truncate text-xs font-semibold text-content-primary">
            {title}
          </p>
          {acknowledged && (
            <Badge variant="neutral" size="sm">
              {t('inbox.acknowledged_badge', { defaultValue: 'Seen' })}
            </Badge>
          )}
          {item.kind === 'approval' && (
            <Badge variant="warning" size="sm">
              {t('inbox.badge_approval', { defaultValue: 'Approval' })}
            </Badge>
          )}
          {timeAgo && (
            <span className="shrink-0 text-2xs tabular-nums text-content-tertiary">{timeAgo}</span>
          )}
        </div>
        {item.project_name && (
          <div className="mt-0.5 truncate text-2xs text-content-tertiary">{item.project_name}</div>
        )}
      </div>
      <SevIcon size={13} className={clsx('shrink-0 mt-0.5', sevStyle.color)} aria-hidden />
      {clickable && (
        <ArrowRight
          size={14}
          className="shrink-0 mt-0.5 text-content-quaternary opacity-0 transition-all group-hover:translate-x-0.5 group-hover:text-oe-blue group-hover:opacity-100"
        />
      )}
    </>
  );

  const acknowledgeLabel = acknowledged
    ? t('inbox.action_unacknowledge', { defaultValue: 'Mark as not seen' })
    : t('inbox.action_acknowledge', { defaultValue: 'Mark as seen' });
  const dismissLabel = t('common.dismiss', { defaultValue: 'Dismiss' });

  return (
    <div
      className={clsx(
        'group flex w-full items-start gap-1 px-2 py-2.5 text-left',
        'border-b border-border-light/60 last:border-b-0 transition-colors',
        clickable && 'hover:bg-surface-secondary',
        acknowledged && 'opacity-60',
      )}
    >
      {/* The navigate target is its own control so the action buttons are not
          nested inside a button, which is invalid and silently breaks clicks. */}
      {clickable ? (
        <button
          type="button"
          onClick={onClick}
          className="flex min-w-0 flex-1 items-start gap-3 rounded-md px-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
        >
          {rowBody}
        </button>
      ) : (
        <div className="flex min-w-0 flex-1 items-start gap-3 px-2">{rowBody}</div>
      )}
      <div className="flex shrink-0 items-center gap-0.5 pt-0.5">
        <button
          type="button"
          onClick={() => action.mutate(acknowledged ? null : 'acknowledged')}
          disabled={action.isPending}
          aria-label={acknowledgeLabel}
          title={acknowledgeLabel}
          className={ROW_ACTION_CLASS}
        >
          {acknowledged ? <Undo2 size={13} /> : <Check size={13} />}
        </button>
        <button
          type="button"
          onClick={() => action.mutate('dismissed')}
          disabled={action.isPending}
          aria-label={dismissLabel}
          title={dismissLabel}
          className={ROW_ACTION_CLASS}
        >
          <X size={13} />
        </button>
      </div>
    </div>
  );
}

export function InboxPanel({
  limit = 8,
  showHeader = true,
  compact = false,
  filter,
}: InboxPanelProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const { data, isLoading, isError, isFetching, refetch } = useInboxQuery(limit);

  // Defensive client-side re-sort (backend already sorts) + approval count.
  const allItems = useMemo(() => sortInboxItems(data?.items ?? []), [data?.items]);
  // The rendered subset: narrowed by the triage filter when the page passes one.
  const items = useMemo(
    () => (filter ? filterInboxItems(allItems, filter) : allItems),
    [allItems, filter],
  );
  // Summary-rail counts stay on the server totals (pre-cap, unfiltered).
  const approvalsCount = data?.approvals_count ?? countApprovals(allItems);
  const alertsCount = data?.alerts_count ?? allItems.length - approvalsCount;
  const total = data?.total ?? allItems.length;
  // Distinguish an empty inbox from "your filter hid everything".
  const filteredEmpty = !isLoading && !isError && allItems.length > 0 && items.length === 0;

  const body = (
    <>
      {isLoading ? (
        <div className="px-4 py-6 space-y-3" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-start gap-2.5">
              <div className="h-7 w-7 rounded-md bg-surface-secondary animate-pulse shrink-0" />
              <div className="flex-1 space-y-1.5">
                <div className="h-2.5 w-3/4 rounded bg-surface-secondary animate-pulse" />
                <div className="h-2 w-1/2 rounded bg-surface-secondary animate-pulse" />
              </div>
            </div>
          ))}
        </div>
      ) : isError ? (
        <div className="px-4 py-6 text-center">
          <XCircle size={20} className="mx-auto mb-2 text-semantic-error" />
          <p className="text-xs text-content-secondary mb-2">
            {t('inbox.load_error', { defaultValue: "Couldn't load your inbox" })}
          </p>
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="inline-flex items-center gap-1 rounded text-2xs font-medium text-oe-blue hover:underline disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
          >
            {isFetching && <Loader2 size={10} className="animate-spin" aria-hidden />}
            {t('common.retry', { defaultValue: 'Try again' })}
          </button>
        </div>
      ) : filteredEmpty ? (
        <div className="px-4 py-8 text-center">
          <Filter size={22} className="mx-auto mb-2 text-content-quaternary" />
          <p className="text-xs font-medium text-content-secondary">
            {t('inbox.filter_empty_title', { defaultValue: 'No items match these filters' })}
          </p>
          <p className="text-2xs text-content-tertiary mt-0.5">
            {t('inbox.filter_empty_desc', {
              defaultValue: 'Try a different segment, project or severity.',
            })}
          </p>
        </div>
      ) : items.length === 0 ? (
        <div className="px-4 py-8 text-center">
          <CheckSquare size={24} className="mx-auto mb-2 text-content-quaternary" />
          <p className="text-xs font-medium text-content-secondary">
            {t('inbox.empty_title', { defaultValue: "You're all caught up" })}
          </p>
          <p className="text-2xs text-content-tertiary mt-0.5">
            {t('inbox.empty_desc', {
              defaultValue: 'Pending approvals and alerts will appear here.',
            })}
          </p>
        </div>
      ) : (
        <div className={clsx('overflow-y-auto', compact ? 'max-h-[360px]' : 'max-h-[640px]')}>
          {items.map((item) => (
            <InboxRow key={item.id} item={item} />
          ))}
        </div>
      )}
    </>
  );

  if (!showHeader) {
    // Page mode: the page supplies the header / chrome; just render the list.
    return (
      <div className="rounded-xl border border-border-light bg-surface-primary overflow-hidden">
        {body}
      </div>
    );
  }

  // ── Dashboard widget mode ──────────────────────────────────────────────
  //    A two-pane card so a sparse inbox never leaves the row mostly empty
  //    (the common case is a handful of items). The list takes the left
  //    side; a compact summary rail - approvals vs alerts + a one-line hint
  //    - fills the right on desktop and folds to a top strip on mobile. The
  //    rail only appears when there are items; the loading, error and
  //    "all caught up" states already center across the full width.
  const hasItems = !isLoading && !isError && items.length > 0;

  const summaryRail = (
    <div className="flex shrink-0 flex-row items-stretch gap-3 border-b border-border-light px-4 py-3 lg:w-52 lg:flex-col lg:gap-3 lg:border-b-0 lg:border-l lg:py-4">
      <button
        type="button"
        onClick={() => navigate('/inbox')}
        className="group flex flex-1 items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-surface-secondary lg:flex-none"
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-semantic-warning-bg">
          <ClipboardCheck size={15} className="text-semantic-warning" />
        </span>
        <span className="min-w-0">
          <span className="block text-lg font-bold leading-none tabular-nums text-content-primary">
            {approvalsCount}
          </span>
          <span className="mt-0.5 block text-2xs text-content-tertiary">
            {t('inbox.approvals_label', { defaultValue: 'approvals' })}
          </span>
        </span>
      </button>
      <button
        type="button"
        onClick={() => navigate('/inbox')}
        className="group flex flex-1 items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-surface-secondary lg:flex-none"
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-oe-blue-subtle">
          <Bell size={15} className="text-oe-blue" />
        </span>
        <span className="min-w-0">
          <span className="block text-lg font-bold leading-none tabular-nums text-content-primary">
            {alertsCount}
          </span>
          <span className="mt-0.5 block text-2xs text-content-tertiary">
            {t('inbox.alerts_label', { defaultValue: 'alerts' })}
          </span>
        </span>
      </button>
      <p className="hidden text-2xs leading-relaxed text-content-tertiary lg:mt-auto lg:block">
        {t('inbox.rail_hint', {
          defaultValue: 'Approvals and alerts that need you, newest first.',
        })}
      </p>
    </div>
  );

  return (
    <Card padding="none">
      <div className="px-4 pb-2 pt-4">
        <CardHeader
          title={
            <span className="inline-flex items-center gap-2">
              <InboxIcon size={16} className="text-oe-blue" strokeWidth={1.75} />
              {t('inbox.title', { defaultValue: 'Inbox' })}
              {total > 0 && (
                <Badge variant="blue" size="sm">
                  {total}
                </Badge>
              )}
            </span>
          }
          action={
            <button
              type="button"
              onClick={() => navigate('/inbox')}
              className="inline-flex items-center gap-1 text-xs font-medium text-content-secondary hover:text-oe-blue transition-colors"
            >
              {t('inbox.view_all', { defaultValue: 'View all' })}
              <ArrowRight size={13} />
            </button>
          }
        />
      </div>
      <div className="flex flex-col lg:flex-row lg:items-stretch">
        <div className="order-2 min-w-0 flex-1 lg:order-1">{body}</div>
        {hasItems && <div className="order-1 lg:order-2">{summaryRail}</div>}
      </div>
    </Card>
  );
}

export default InboxPanel;

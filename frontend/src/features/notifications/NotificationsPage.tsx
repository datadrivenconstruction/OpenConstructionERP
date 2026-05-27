/**
 * NotificationsPage — full notification inbox.
 *
 * Linked from the header bell's "View all" footer. Adds what the bell
 * dropdown can't fit: pagination, read/unread filter, and bulk actions.
 *
 * Endpoints used (all per backend/app/modules/notifications/router.py):
 *   GET    /v1/notifications/?limit=50&offset=N&is_read=true|false
 *   POST   /v1/notifications/{id}/read/
 *   POST   /v1/notifications/read-all/
 *   DELETE /v1/notifications/{id}
 *
 * The page mirrors the bell's icon palette + grouping so a user who
 * clicks through from the dropdown lands on a familiar layout.
 */

import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Bell,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Info,
  Upload,
  Shield,
  Settings,
  Loader2,
  Trash2,
  Filter,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import clsx from 'clsx';
import { Button, Breadcrumb, EmptyState, DateDisplay, SkeletonTable } from '@/shared/ui';
import { apiGet, apiPost, apiDelete } from '@/shared/lib/api';
import { PreferencesTab } from './PreferencesTab';

type Tab = 'inbox' | 'preferences';

type IconCategory =
  | 'success'
  | 'error'
  | 'warning'
  | 'info'
  | 'import'
  | 'validation'
  | 'system';

interface Notification {
  id: string;
  notification_type: string;
  icon_category: IconCategory;
  title_key: string;
  title_default: string;
  body_key?: string | null;
  body_default: string;
  body_context: Record<string, unknown>;
  action_url?: string | null;
  is_read: boolean;
  created_at: string;
}

interface NotificationListResponse {
  items: Notification[];
  total: number;
  unread_count: number;
}

const ICON_MAP: Record<IconCategory, { icon: typeof CheckCircle2; color: string; bg: string }> = {
  success: {
    icon: CheckCircle2,
    color: 'text-semantic-success',
    bg: 'bg-emerald-50 dark:bg-emerald-900/30',
  },
  error: { icon: XCircle, color: 'text-semantic-error', bg: 'bg-rose-50 dark:bg-rose-900/30' },
  warning: { icon: AlertTriangle, color: 'text-amber-500', bg: 'bg-amber-50 dark:bg-amber-900/30' },
  info: { icon: Info, color: 'text-oe-blue-text', bg: 'bg-oe-blue-subtle' },
  import: { icon: Upload, color: 'text-indigo-500', bg: 'bg-indigo-50 dark:bg-indigo-900/30' },
  validation: { icon: Shield, color: 'text-purple-500', bg: 'bg-purple-50 dark:bg-purple-900/30' },
  system: { icon: Settings, color: 'text-content-tertiary', bg: 'bg-surface-secondary' },
};

const ACTION_URL_REWRITES: Array<[RegExp, (m: RegExpMatchArray) => string]> = [
  [/^\/risk(\?.*)?$/, (m) => `/risks${m[1] ?? ''}`],
  [/^\/boq\?id=([0-9a-fA-F-]{8,})$/, (m) => `/boq/${m[1]}`],
];

function normalizeActionUrl(url: string): string {
  for (const [re, build] of ACTION_URL_REWRITES) {
    const m = url.match(re);
    if (m) return build(m);
  }
  return url;
}

/* Last-resort label for a notification whose i18n key is missing from the
   active locale AND has no server-side default. Turn the final segment of a
   dotted key (e.g. "notifications.safety.incident_created_body") into a
   readable sentence ("Incident created") instead of printing the raw path.
   Generic by design — the per-message copy still lives in the locale files;
   this only keeps an un-localised key from leaking to the user. */
function humanizeKey(key: string): string {
  const segment = key.split('.').pop() ?? key;
  const words = segment
    .replace(/_body$/i, '')
    .replace(/_title$/i, '')
    .replace(/[._]+/g, ' ')
    .trim();
  if (!words) return '';
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const PAGE_SIZE = 50;

type NotificationFilter = 'all' | 'unread' | 'read';

export function NotificationsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState<Tab>('inbox');
  const [filter, setFilter] = useState<NotificationFilter>('all');
  const [page, setPage] = useState(0);

  /* The backend's `is_read` query param is tri-state: `undefined` =
     don't filter, `true` = only read, `false` = only unread. */
  const isReadParam: boolean | undefined =
    filter === 'all' ? undefined : filter === 'read' ? true : false;

  const queryKey = ['notifications-page', filter, page];
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey,
    queryFn: () => {
      const params = new URLSearchParams();
      params.set('limit', String(PAGE_SIZE));
      params.set('offset', String(page * PAGE_SIZE));
      if (isReadParam !== undefined) params.set('is_read', String(isReadParam));
      return apiGet<NotificationListResponse>(`/v1/notifications?${params.toString()}`);
    },
    staleTime: 10_000,
    refetchOnWindowFocus: true,
    enabled: activeTab === 'inbox',
  });

  const items: Notification[] = useMemo(() => data?.items ?? [], [data]);
  const total = data?.total ?? 0;
  const unreadCount = data?.unread_count ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const markReadMutation = useMutation({
    mutationFn: (id: string) => apiPost<void>(`/v1/notifications/${id}/read/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications-page'] });
      queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] });
      queryClient.invalidateQueries({ queryKey: ['notifications-list'] });
    },
  });

  const markAllReadMutation = useMutation({
    mutationFn: () => apiPost<void>('/v1/notifications/read-all/'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications-page'] });
      queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] });
      queryClient.invalidateQueries({ queryKey: ['notifications-list'] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/notifications/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications-page'] });
      queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] });
      queryClient.invalidateQueries({ queryKey: ['notifications-list'] });
    },
  });

  const handleRowClick = useCallback(
    (n: Notification) => {
      if (!n.is_read) markReadMutation.mutate(n.id);
      if (n.action_url) navigate(normalizeActionUrl(n.action_url));
    },
    [markReadMutation, navigate],
  );

  return (
    <div className="w-full animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', 'Dashboard'), to: '/' },
          { label: t('notifications.title', 'Notifications') },
        ]}
        className="mb-3"
      />

      {/* Tab bar — Inbox vs Preferences.  The preferences tab houses the
          per-event-type × per-channel routing matrix added in Wave 3 / T9. */}
      <div className="mb-3 border-b border-border-light flex items-center gap-1">
        <button
          type="button"
          onClick={() => setActiveTab('inbox')}
          className={clsx(
            'px-3 py-1.5 text-sm font-medium border-b-2 -mb-px transition-colors',
            activeTab === 'inbox'
              ? 'border-oe-blue text-oe-blue'
              : 'border-transparent text-content-secondary hover:text-content-primary',
          )}
          aria-current={activeTab === 'inbox' ? 'page' : undefined}
        >
          {t('notifications.tab_inbox', { defaultValue: 'Inbox' })}
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('preferences')}
          className={clsx(
            'px-3 py-1.5 text-sm font-medium border-b-2 -mb-px transition-colors',
            activeTab === 'preferences'
              ? 'border-oe-blue text-oe-blue'
              : 'border-transparent text-content-secondary hover:text-content-primary',
          )}
          aria-current={activeTab === 'preferences' ? 'page' : undefined}
        >
          {t('notifications.tab_preferences', { defaultValue: 'Preferences' })}
        </button>
      </div>

      {activeTab === 'preferences' ? (
        <PreferencesTab />
      ) : (
      <>
      {/* Page header — compact: icon + title + unread chip + filter dropdown
          + Mark-all-read. Mirrors the bell's style so the user lands on a
          familiar visual. */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="shrink-0 w-7 h-7 rounded-lg bg-gradient-to-br from-oe-blue to-sky-500 text-white inline-flex items-center justify-center shadow-sm">
            <Bell className="w-3.5 h-3.5" />
          </span>
          <h1 className="text-base lg:text-lg leading-none font-semibold text-content-primary">
            {t('notifications.title', 'Notifications')}
          </h1>
          {total > 0 && (
            <span className="text-xs text-content-tertiary tabular-nums">
              {total} {t('notifications.total', { defaultValue: 'total' })}
            </span>
          )}
          {unreadCount > 0 && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-2xs font-semibold bg-oe-blue-subtle text-oe-blue-text tabular-nums">
              {unreadCount} {t('notifications.unread', { defaultValue: 'unread' })}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Filter
              size={13}
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-content-tertiary pointer-events-none"
            />
            <select
              value={filter}
              onChange={(e) => {
                setFilter(e.target.value as NotificationFilter);
                setPage(0);
              }}
              className="h-9 ps-8 pe-3 text-xs rounded-lg border border-border bg-surface-primary text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/40"
            >
              <option value="all">{t('notifications.filter_all', { defaultValue: 'All' })}</option>
              <option value="unread">
                {t('notifications.filter_unread', { defaultValue: 'Unread only' })}
              </option>
              <option value="read">
                {t('notifications.filter_read', { defaultValue: 'Read only' })}
              </option>
            </select>
          </div>
          {unreadCount > 0 && (
            <Button
              variant="secondary"
              size="sm"
              icon={<CheckCircle2 size={14} />}
              onClick={() => markAllReadMutation.mutate()}
              disabled={markAllReadMutation.isPending}
            >
              {t('notifications.mark_all_read_short', { defaultValue: 'Mark all read' })}
            </Button>
          )}
        </div>
      </div>

      {/* List */}
      <div className="rounded-xl border border-border-light bg-surface-elevated overflow-hidden">
        {isLoading ? (
          <SkeletonTable rows={6} columns={3} className="border-0 rounded-none" />
        ) : isError ? (
          <div className="p-8 text-center">
            <XCircle size={24} className="mx-auto mb-2 text-semantic-error" />
            <p className="text-sm text-content-secondary mb-3">
              {t('notifications.load_error', { defaultValue: "Couldn't load notifications" })}
            </p>
            <Button variant="secondary" size="sm" onClick={() => refetch()}>
              {t('common.retry', { defaultValue: 'Try again' })}
            </Button>
          </div>
        ) : items.length === 0 ? (
          <div className="p-12">
            <EmptyState
              icon={<Bell size={28} strokeWidth={1.5} />}
              title={
                filter === 'unread'
                  ? t('notifications.no_unread', { defaultValue: 'No unread notifications' })
                  : filter === 'read'
                  ? t('notifications.no_read', { defaultValue: 'No read notifications yet' })
                  : t('notifications.all_caught_up', { defaultValue: "You're all caught up" })
              }
              description={t('notifications.no_notifications_hint', {
                defaultValue: "We'll let you know when something needs your attention.",
              })}
            />
          </div>
        ) : (
          <ul role="list" className="divide-y divide-border-light">
            {items.map((n) => {
              const cfg = ICON_MAP[n.icon_category] ?? ICON_MAP.info;
              const TypeIcon = cfg.icon;
              const title = t(n.title_key, {
                defaultValue: n.title_default || humanizeKey(n.title_key),
                ...(n.body_context as Record<string, unknown>),
              });
              const body = n.body_key
                ? t(n.body_key, {
                    defaultValue: n.body_default || humanizeKey(n.body_key),
                    ...(n.body_context as Record<string, unknown>),
                  })
                : n.body_default;
              const deleting = deleteMutation.isPending && deleteMutation.variables === n.id;
              return (
                <li
                  key={n.id}
                  className={clsx(
                    'group flex items-start gap-3 px-4 py-3',
                    'hover:bg-surface-secondary/60 transition-colors',
                    !n.is_read && 'bg-oe-blue-subtle/30',
                    deleting && 'opacity-50 pointer-events-none',
                  )}
                >
                  <button
                    type="button"
                    onClick={() => handleRowClick(n)}
                    className="flex items-start gap-3 flex-1 min-w-0 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 rounded-md -m-1 p-1"
                  >
                    <span
                      className={clsx(
                        'shrink-0 h-9 w-9 rounded-lg flex items-center justify-center',
                        cfg.bg,
                      )}
                    >
                      <TypeIcon size={16} className={cfg.color} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline gap-2 flex-wrap">
                        <p
                          className={clsx(
                            'text-sm leading-snug',
                            n.is_read
                              ? 'font-medium text-content-primary'
                              : 'font-semibold text-content-primary',
                          )}
                        >
                          {title}
                        </p>
                        {!n.is_read && (
                          <span className="inline-block h-2 w-2 rounded-full bg-oe-blue shrink-0" />
                        )}
                      </div>
                      {body && (
                        <p className="text-xs text-content-secondary mt-0.5">{body}</p>
                      )}
                      <p className="text-[11px] text-content-quaternary mt-1 tabular-nums">
                        <DateDisplay value={n.created_at} format="datetime" />
                      </p>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteMutation.mutate(n.id)}
                    className={clsx(
                      'shrink-0 flex h-7 w-7 items-center justify-center rounded-md',
                      'text-content-quaternary',
                      'opacity-0 group-hover:opacity-100 focus:opacity-100',
                      'hover:bg-rose-50 hover:text-rose-500 dark:hover:bg-rose-900/30',
                      'transition-all',
                    )}
                    title={t('common.delete', { defaultValue: 'Delete' })}
                    aria-label={t('common.delete', { defaultValue: 'Delete' })}
                  >
                    {deleting ? (
                      <Loader2 size={13} className="animate-spin" />
                    ) : (
                      <Trash2 size={13} />
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Pagination — only visible when there's more than a page of data
          AND the request didn't error. */}
      {totalPages > 1 && (
        <div className="mt-3 flex items-center justify-between text-xs text-content-tertiary">
          <span>
            {t('common.showing_range', {
              defaultValue: 'Showing {{from}}-{{to}} of {{total}}',
              from: page * PAGE_SIZE + 1,
              to: Math.min((page + 1) * PAGE_SIZE, total),
              total,
            })}
          </span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="h-8 w-8 inline-flex items-center justify-center rounded-md border border-border-light text-content-secondary hover:bg-surface-secondary disabled:opacity-40 disabled:cursor-not-allowed"
              aria-label={t('common.previous', { defaultValue: 'Previous' })}
            >
              <ChevronLeft size={14} />
            </button>
            <span className="px-2 tabular-nums">
              {page + 1} / {totalPages}
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="h-8 w-8 inline-flex items-center justify-center rounded-md border border-border-light text-content-secondary hover:bg-surface-secondary disabled:opacity-40 disabled:cursor-not-allowed"
              aria-label={t('common.next', { defaultValue: 'Next' })}
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
      </>
      )}
    </div>
  );
}

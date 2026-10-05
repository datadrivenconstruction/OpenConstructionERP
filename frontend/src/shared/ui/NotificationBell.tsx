// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * NotificationBell — header bell icon with unread badge and dropdown panel.
 *
 * Uses React Query to poll /api/v1/notifications/unread-count every 30s and
 * also refetches on tab focus so the bell never lags more than one tab-switch
 * behind reality. Dropdown shows last 10 notifications from
 * /api/v1/notifications, grouped by date (Today / Yesterday / Earlier).
 *
 * Each row supports inline mark-read (via row click) + delete (via hover X).
 * "View all" leads to /notifications for a paginated history with filters.
 */

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNotificationsWebSocket } from './useNotificationsWebSocket';
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
  X,
  ArrowRight,
} from 'lucide-react';
import clsx from 'clsx';
import { apiGet, apiPost, apiDelete, ApiError, type Page } from '@/shared/lib/api';
import { normalizeActionUrl } from '@/shared/lib/notificationActionUrl';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';

// ── Types ────────────────────────────────────────────────────────────────────

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

interface UnreadCountResponse {
  count: number;
}


// ── Icon config ──────────────────────────────────────────────────────────────

const NOTIFICATION_ICON_MAP: Record<
  IconCategory,
  { icon: typeof CheckCircle2; colorClass: string; bgClass: string }
> = {
  success: {
    icon: CheckCircle2,
    colorClass: 'text-semantic-success',
    bgClass: 'bg-emerald-50 dark:bg-emerald-900/30',
  },
  error: {
    icon: XCircle,
    colorClass: 'text-semantic-error',
    bgClass: 'bg-rose-50 dark:bg-rose-900/30',
  },
  warning: {
    icon: AlertTriangle,
    colorClass: 'text-amber-500',
    bgClass: 'bg-amber-50 dark:bg-amber-900/30',
  },
  info: {
    icon: Info,
    colorClass: 'text-oe-blue',
    bgClass: 'bg-oe-blue-subtle',
  },
  import: {
    icon: Upload,
    colorClass: 'text-indigo-500',
    bgClass: 'bg-indigo-50 dark:bg-indigo-900/30',
  },
  validation: {
    icon: Shield,
    colorClass: 'text-purple-500',
    bgClass: 'bg-purple-50 dark:bg-purple-900/30',
  },
  system: {
    icon: Settings,
    colorClass: 'text-content-tertiary',
    bgClass: 'bg-surface-secondary',
  },
};

function getIconConfig(category: IconCategory) {
  return NOTIFICATION_ICON_MAP[category] ?? NOTIFICATION_ICON_MAP.info;
}

// ── Time formatting ──────────────────────────────────────────────────────────

function formatTimeAgo(
  dateStr: string,
  t: ReturnType<typeof useTranslation>['t'],
): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return t('notifications.just_now', { defaultValue: 'Just now' });
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60)
    return t('time.minutes_ago', { defaultValue: '{{count}}m ago', count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t('time.hours_ago', { defaultValue: '{{count}}h ago', count: hours });
  const days = Math.floor(hours / 24);
  return t('time.days_ago', { defaultValue: '{{count}}d ago', count: days });
}

/** Bucket a notification by date. Used to group the list visually in the
    dropdown so the user can scan "what's new today" without reading every
    row's timestamp. */
type DateBucket = 'today' | 'yesterday' | 'earlier';

function bucketFor(dateStr: string): DateBucket {
  const created = new Date(dateStr);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startOfYesterday = startOfToday - 24 * 60 * 60 * 1000;
  const t = created.getTime();
  if (t >= startOfToday) return 'today';
  if (t >= startOfYesterday) return 'yesterday';
  return 'earlier';
}

// ── Component ────────────────────────────────────────────────────────────────

export function NotificationBell() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  /* Polling cadence — 30s in the background, refetch on tab focus so the
     bell never lags more than one tab-switch behind. retry:false because
     an unread-count failure shouldn't spam the network on every render. */
  const { data: unreadData } = useQuery({
    queryKey: ['notifications-unread-count'],
    queryFn: () => apiGet<UnreadCountResponse>('/v1/notifications/unread-count/'),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
    staleTime: 15_000,
    retry: false,
  });

  const unreadCount = unreadData?.count ?? 0;

  /* Epic B / B10: sub-second push via /api/v1/notifications/ws/.
     On a `notification.created` event we invalidate both queries so
     the bell jumps immediately — the 30s polling cadence stays as a
     belt-and-braces fallback for proxies that drop WS connections. */
  useNotificationsWebSocket({
    enabled: true,
    onNotification: useCallback(
      (evt: { event: string }) => {
        if (evt.event === 'notification.created') {
          queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] });
          queryClient.invalidateQueries({ queryKey: ['notifications-list'] });
        }
      },
      [queryClient],
    ),
  });

  /* List query only fires when the dropdown opens. The server returns the
     shared `Page` envelope plus this module's unread counter, so `total` is
     the size of the whole history behind the ten rows shown here. */
  const {
    data: notifications,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['notifications-list'],
    queryFn: () =>
      apiGet<Page<Notification> & { unread_count: number }>(
        '/v1/notifications?limit=10',
      ),
    enabled: open,
    staleTime: 10_000,
    refetchOnWindowFocus: true,
    retry: false,
  });

  const markReadMutation = useMutation({
    mutationFn: (id: string) => apiPost<void>(`/v1/notifications/${id}/read/`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] });
      queryClient.invalidateQueries({ queryKey: ['notifications-list'] });
    },
    onError: (err: Error) => {
      console.warn('Failed to mark notification as read:', err.message);
    },
  });

  const markAllReadMutation = useMutation({
    mutationFn: () => apiPost<void>('/v1/notifications/read-all/'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] });
      queryClient.invalidateQueries({ queryKey: ['notifications-list'] });
    },
    onError: (err: Error) => {
      console.warn('Failed to mark all notifications as read:', err.message);
    },
  });

  /* DELETE removes the row entirely (different from mark-read which only
     flips the flag). Used by the small X button that appears on row hover. */
  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiDelete(`/v1/notifications/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] });
      queryClient.invalidateQueries({ queryKey: ['notifications-list'] });
    },
    onError: (err: Error) => {
      console.warn('Failed to delete notification:', err.message);
    },
  });

  // Close on click outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open]);

  const handleToggle = useCallback(() => {
    setOpen((prev) => !prev);
  }, []);

  const handleNotificationClick = useCallback(
    (notification: Notification) => {
      if (!notification.is_read) {
        markReadMutation.mutate(notification.id);
      }
      /* Always close the dropdown on click — pre-rewrite the panel stayed
         open when a notification had no action_url, which felt broken
         (the row visibly went read but nothing else happened). */
      setOpen(false);
      if (notification.action_url) {
        navigate(normalizeActionUrl(notification.action_url));
      }
    },
    [markReadMutation, navigate],
  );

  const handleDeleteNotification = useCallback(
    (e: React.MouseEvent, id: string) => {
      e.stopPropagation();
      deleteMutation.mutate(id);
    },
    [deleteMutation],
  );

  const handleMarkAllRead = useCallback(() => {
    markAllReadMutation.mutate();
    /* Close after the mutation kicks off — the optimistic UX is "panel
       went away, badge went to 0". The cache invalidation reconciles on
       the next open. */
    setOpen(false);
  }, [markAllReadMutation]);

  const handleViewAll = useCallback(() => {
    setOpen(false);
    navigate('/notifications');
  }, [navigate]);

  /* Tolerate the bare-array legacy shape so an older backend doesn't
     bork the bell — the envelope is preferred but historically the
     endpoint returned a raw list. */
  const displayItems: Notification[] = useMemo(() => {
    if (!notifications) return [];
    if (Array.isArray(notifications)) return notifications as Notification[];
    return notifications.items ?? [];
  }, [notifications]);

  /* Group by date bucket so the dropdown reads like "Today / Yesterday /
     Earlier" instead of a flat list with timestamps the user has to parse
     row-by-row. */
  const grouped = useMemo(() => {
    const buckets: Record<DateBucket, Notification[]> = {
      today: [],
      yesterday: [],
      earlier: [],
    };
    for (const n of displayItems) buckets[bucketFor(n.created_at)].push(n);
    return buckets;
  }, [displayItems]);

  const totalCount = Array.isArray(notifications)
    ? displayItems.length
    : (notifications?.total ?? 0);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={handleToggle}
        aria-expanded={open}
        aria-haspopup="menu"
        className={clsx(
          /* h-9 w-9 gives us a 36×36 hit area — still compact in the header
             but closer to the 44px mobile-tap-target guideline than the
             previous 32×32. */
          'flex h-9 w-9 items-center justify-center rounded-lg',
          'text-content-secondary transition-all duration-fast ease-oe',
          'hover:bg-surface-secondary hover:text-content-primary',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40',
          open && 'bg-surface-secondary text-content-primary',
        )}
        title={t('notifications.title', { defaultValue: 'Notifications' })}
        aria-label={t('notifications.title', { defaultValue: 'Notifications' })}
      >
        <Bell size={16} strokeWidth={1.75} />
        {unreadCount > 0 && (
          <span
            className={clsx(
              'absolute -top-0.5 -right-0.5 flex h-4 min-w-[16px] items-center justify-center',
              'rounded-full bg-semantic-error px-1 text-[10px] font-bold text-white',
            )}
          >
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div
          role="menu"
          /* z-50 lifts the dropdown above sticky headers, sidebars, and any
             modal scrim that might have been left below. The previous
             stack omitted z-index so it was sometimes covered by overlays.
             Max width on small screens prevents off-screen clipping. */
          className={clsx(
            'absolute right-0 top-full mt-1.5 z-50',
            'w-[min(360px,calc(100vw-1rem))]',
            'rounded-xl border border-border-light bg-surface-elevated shadow-xl',
            'animate-scale-in overflow-hidden',
          )}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-light">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-content-primary">
                {t('notifications.title', { defaultValue: 'Notifications' })}
              </span>
              {totalCount > 0 && (
                <span className="text-2xs text-content-quaternary tabular-nums">
                  {totalCount}
                </span>
              )}
            </div>
            {unreadCount > 0 && !isLoading && (
              <button
                onClick={handleMarkAllRead}
                disabled={markAllReadMutation.isPending}
                className="text-2xs font-medium text-oe-blue hover:underline disabled:opacity-50 inline-flex items-center gap-1"
              >
                {markAllReadMutation.isPending && <Loader2 size={10} className="animate-spin" />}
                {t('notifications.mark_all_read_short', { defaultValue: 'Mark all read' })}
              </button>
            )}
          </div>

          {/* Body — loading / error / empty / list */}
          {isLoading ? (
            <div className="px-4 py-6 space-y-3" aria-busy="true">
              {[0, 1, 2].map((i) => (
                <div key={i} className="flex items-start gap-2.5">
                  <div className="h-7 w-7 rounded-md bg-surface-secondary animate-pulse shrink-0" />
                  <div className="flex-1 space-y-1.5">
                    <div className="h-2.5 w-3/4 rounded bg-surface-secondary animate-pulse" />
                    <div className="h-2 w-full rounded bg-surface-secondary animate-pulse" />
                  </div>
                </div>
              ))}
            </div>
          ) : isError ? (
            <div className="px-4 py-6 text-center">
              <XCircle size={20} className="mx-auto mb-2 text-semantic-error" />
              <p className="text-xs text-content-secondary mb-2">
                {t('notifications.load_error', { defaultValue: "Couldn't load notifications" })}
              </p>
              {error instanceof ApiError && error.status === 401 ? (
                <p className="text-2xs text-content-tertiary">
                  {t('notifications.load_error_auth', {
                    defaultValue: 'Please sign in again to view your notifications.',
                  })}
                </p>
              ) : (
                <button
                  onClick={() => refetch()}
                  className="text-2xs font-medium text-oe-blue hover:underline"
                >
                  {t('common.retry', { defaultValue: 'Try again' })}
                </button>
              )}
            </div>
          ) : displayItems.length === 0 ? (
            <div className="px-4 py-8 text-center">
              <Bell size={24} className="mx-auto mb-2 text-content-quaternary" />
              <p className="text-xs text-content-secondary font-medium">
                {t('notifications.all_caught_up', { defaultValue: "You're all caught up" })}
              </p>
              <p className="text-2xs text-content-tertiary mt-0.5">
                {t('notifications.no_notifications_hint', {
                  defaultValue: "We'll let you know when something needs your attention.",
                })}
              </p>
            </div>
          ) : (
            <div className="max-h-[420px] overflow-y-auto">
              {(['today', 'yesterday', 'earlier'] as const).map((bucket) => {
                const rows = grouped[bucket];
                if (rows.length === 0) return null;
                const bucketLabel = t(`notifications.bucket.${bucket}`, {
                  defaultValue:
                    bucket === 'today'
                      ? 'Today'
                      : bucket === 'yesterday'
                      ? 'Yesterday'
                      : 'Earlier',
                });
                return (
                  <div key={bucket}>
                    <div className="sticky top-0 z-10 bg-surface-elevated/95 backdrop-blur px-4 py-1.5 text-[10px] uppercase tracking-wider font-semibold text-content-quaternary border-b border-border-light/60">
                      {bucketLabel}
                    </div>
                    {rows.map((notification) => {
                      const config = getIconConfig(notification.icon_category);
                      const TypeIcon = config.icon;
                      /* Root cause of CRAWL-NOTIFBELL: a notification row
                         whose `title_key`/`body_key` is null or a non-string
                         (a malformed/legacy DB row, or a future backend
                         shape change) was passed straight into i18next's
                         `t()`. i18next internally does `key.split(...)`, so a
                         null key throws a TypeError that escapes render and
                         is caught by the route ErrorBoundary — the bell
                         "crashes the page" on any route. Coerce the key to a
                         safe string and fall back to the human-readable
                         default text, and tolerate a null `body_context`
                         (object spread of null is fine, but be explicit). */
                      const titleKey =
                        typeof notification.title_key === 'string' &&
                        notification.title_key
                          ? notification.title_key
                          : '';
                      const bodyKey =
                        typeof notification.body_key === 'string' &&
                        notification.body_key
                          ? notification.body_key
                          : '';
                      const ctx =
                        notification.body_context &&
                        typeof notification.body_context === 'object'
                          ? (notification.body_context as Record<string, unknown>)
                          : {};
                      const title = titleKey
                        ? t(titleKey, {
                            defaultValue:
                              notification.title_default || titleKey,
                            ...ctx,
                          })
                        : notification.title_default || '';
                      const body = bodyKey
                        ? t(bodyKey, {
                            defaultValue: notification.body_default,
                            ...ctx,
                          })
                        : notification.body_default;
                      const deleting =
                        deleteMutation.isPending &&
                        deleteMutation.variables === notification.id;
                      return (
                        <div
                          key={notification.id}
                          className={clsx(
                            'group relative flex items-start gap-2.5 px-4 py-2.5 text-left',
                            'hover:bg-surface-secondary transition-colors',
                            'border-b border-border-light/60 last:border-b-0',
                            !notification.is_read && 'bg-oe-blue-subtle/30',
                            deleting && 'opacity-50 pointer-events-none',
                          )}
                        >
                          {/* The whole row is the click-target; nested
                              delete button uses stopPropagation. Using a
                              <button> as the outer for a11y. */}
                          <button
                            type="button"
                            onClick={() => handleNotificationClick(notification)}
                            className="flex items-start gap-2.5 flex-1 min-w-0 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40 rounded-md -m-1 p-1"
                          >
                            <span
                              className={clsx(
                                'shrink-0 h-7 w-7 rounded-md flex items-center justify-center',
                                config.bgClass,
                              )}
                            >
                              <TypeIcon size={14} className={config.colorClass} />
                            </span>
                            <div className="min-w-0 flex-1">
                              <p
                                className={clsx(
                                  'text-xs leading-snug line-clamp-1',
                                  notification.is_read
                                    ? 'font-medium text-content-primary'
                                    : 'font-semibold text-content-primary',
                                )}
                              >
                                {title}
                              </p>
                              {body && (
                                <p className="text-2xs text-content-tertiary line-clamp-2 mt-0.5">
                                  {body}
                                </p>
                              )}
                              <p className="text-[10px] text-content-quaternary mt-1 tabular-nums">
                                {formatTimeAgo(notification.created_at, t)}
                              </p>
                            </div>
                            {!notification.is_read && (
                              <span
                                className="shrink-0 mt-1 h-2 w-2 rounded-full bg-oe-blue"
                                aria-label={t('notifications.unread', { defaultValue: 'unread' })}
                                title={t('notifications.unread', { defaultValue: 'unread' })}
                              />
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={(e) => handleDeleteNotification(e, notification.id)}
                            className={clsx(
                              'shrink-0 flex h-6 w-6 items-center justify-center rounded-md',
                              'text-content-quaternary',
                              'opacity-0 group-hover:opacity-100 focus:opacity-100',
                              'hover:bg-rose-50 hover:text-rose-500 dark:hover:bg-rose-900/30',
                              'transition-all',
                            )}
                            title={t('common.delete', { defaultValue: 'Delete' })}
                            aria-label={t('common.delete', { defaultValue: 'Delete' })}
                          >
                            {deleting ? (
                              <Loader2 size={12} className="animate-spin" />
                            ) : (
                              <Trash2 size={11} />
                            )}
                          </button>
                        </div>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          )}

          {/* Footer — View all link (always visible so user can find the
              full history even when the bell only has 0 unread). */}
          <div className="border-t border-border-light px-4 py-2 bg-surface-secondary/40">
            {/* The header chip states the size of the whole history, which on
                its own reads as a count of what is in the panel. Saying how
                many of them are on screen puts the number and the ten rows
                below it in the same sentence, right above the way out to the
                rest. Renders nothing when the ten rows are all there is. */}
            {notifications && (
              <TruncationNotice
                page={{ items: displayItems, total: totalCount }}
                className="mb-1 text-center"
              />
            )}
            <button
              onClick={handleViewAll}
              className="flex w-full items-center justify-center gap-1.5 rounded-lg py-1.5 text-xs font-medium text-content-secondary hover:text-oe-blue hover:bg-surface-elevated transition-colors"
            >
              {t('notifications.view_all', { defaultValue: 'View all notifications' })}
              <ArrowRight size={12} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// Re-export X so existing consumers that pulled in the old icon set don't break.
export { X };

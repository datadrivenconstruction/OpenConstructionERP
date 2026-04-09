/**
 * NotificationBell — header bell icon with unread badge and dropdown panel.
 *
 * Uses React Query to poll /api/v1/notifications/unread-count every 30 seconds.
 * Dropdown shows last 10 notifications from /api/v1/notifications.
 * Clicking a notification marks it as read and navigates to its action_url.
 */

import { useState, useRef, useEffect, useCallback } from 'react';
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
} from 'lucide-react';
import clsx from 'clsx';
import { apiGet, apiPost } from '@/shared/lib/api';

// ── Types ────────────────────────────────────────────────────────────────────

interface Notification {
  id: string;
  type: 'success' | 'error' | 'warning' | 'info' | 'import' | 'validation' | 'system';
  title_key: string;
  title_default: string;
  message?: string;
  action_url?: string;
  read: boolean;
  created_at: string;
}

interface UnreadCountResponse {
  count: number;
}

// ── Icon config ──────────────────────────────────────────────────────────────

const NOTIFICATION_ICON_MAP: Record<
  Notification['type'],
  { icon: typeof CheckCircle2; colorClass: string }
> = {
  success: { icon: CheckCircle2, colorClass: 'text-semantic-success' },
  error: { icon: XCircle, colorClass: 'text-semantic-error' },
  warning: { icon: AlertTriangle, colorClass: 'text-amber-500' },
  info: { icon: Info, colorClass: 'text-oe-blue' },
  import: { icon: Upload, colorClass: 'text-indigo-500' },
  validation: { icon: Shield, colorClass: 'text-purple-500' },
  system: { icon: Settings, colorClass: 'text-content-tertiary' },
};

function getIconConfig(type: Notification['type']) {
  return NOTIFICATION_ICON_MAP[type] ?? NOTIFICATION_ICON_MAP.info;
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

// ── Component ────────────────────────────────────────────────────────────────

export function NotificationBell() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Poll unread count every 30 seconds
  const { data: unreadData } = useQuery({
    queryKey: ['notifications-unread-count'],
    queryFn: () => apiGet<UnreadCountResponse>('/v1/notifications/unread-count/'),
    refetchInterval: 30_000,
    staleTime: 15_000,
    retry: false,
  });

  const unreadCount = unreadData?.count ?? 0;

  // Fetch last 10 notifications when dropdown opens
  const { data: notifications } = useQuery({
    queryKey: ['notifications-list'],
    queryFn: () => apiGet<Notification[]>('/v1/notifications?limit=10'),
    enabled: open,
    staleTime: 10_000,
    retry: false,
  });

  // Mark single notification as read
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

  // Mark all as read
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
      if (!notification.read) {
        markReadMutation.mutate(notification.id);
      }
      if (notification.action_url) {
        navigate(notification.action_url);
        setOpen(false);
      }
    },
    [markReadMutation, navigate],
  );

  const handleMarkAllRead = useCallback(() => {
    markAllReadMutation.mutate();
  }, [markAllReadMutation]);

  const displayItems = notifications ?? [];

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={handleToggle}
        aria-expanded={open}
        aria-haspopup="true"
        className={clsx(
          'flex h-8 w-8 items-center justify-center rounded-lg',
          'text-content-secondary transition-all duration-fast ease-oe',
          'hover:bg-surface-secondary hover:text-content-primary',
          open && 'bg-surface-secondary text-content-primary',
        )}
        title={t('notifications.title', { defaultValue: 'Notifications' })}
        aria-label={t('notifications.title', { defaultValue: 'Notifications' })}
      >
        <Bell size={16} strokeWidth={1.75} />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-semantic-error px-1 text-[10px] font-bold text-white">
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full mt-1.5 w-80 rounded-xl border border-border-light bg-surface-elevated shadow-lg animate-scale-in overflow-hidden"
        >
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-light">
            <span className="text-xs font-semibold text-content-primary">
              {t('notifications.title', { defaultValue: 'Notifications' })}
            </span>
            {unreadCount > 0 && (
              <span className="text-2xs text-content-tertiary">
                {unreadCount} {t('notifications.unread', { defaultValue: 'unread' })}
              </span>
            )}
          </div>

          {/* Items */}
          {displayItems.length === 0 ? (
            <div className="px-4 py-8 text-center">
              <Bell size={24} className="mx-auto mb-2 text-content-quaternary" />
              <p className="text-xs text-content-tertiary">
                {t('notifications.no_notifications', { defaultValue: 'No new notifications' })}
              </p>
            </div>
          ) : (
            <div className="max-h-80 overflow-y-auto">
              {displayItems.map((notification) => {
                const config = getIconConfig(notification.type);
                const TypeIcon = config.icon;
                return (
                  <button
                    key={notification.id}
                    type="button"
                    onClick={() => handleNotificationClick(notification)}
                    className={clsx(
                      'flex w-full items-start gap-2.5 px-4 py-2.5 text-left',
                      'hover:bg-surface-secondary transition-colors',
                      'border-b border-border-light last:border-b-0',
                      !notification.read && 'border-l-2 border-l-oe-blue',
                    )}
                  >
                    <TypeIcon
                      size={15}
                      className={clsx('shrink-0 mt-0.5', config.colorClass)}
                    />
                    <div className="min-w-0 flex-1">
                      <p
                        className={clsx(
                          'text-xs truncate',
                          notification.read
                            ? 'font-medium text-content-primary'
                            : 'font-semibold text-content-primary',
                        )}
                      >
                        {t(notification.title_key, {
                          defaultValue: notification.title_default,
                        })}
                      </p>
                      {notification.message && (
                        <p className="text-2xs text-content-tertiary truncate mt-0.5">
                          {notification.message}
                        </p>
                      )}
                    </div>
                    <span className="text-2xs text-content-quaternary whitespace-nowrap shrink-0">
                      {formatTimeAgo(notification.created_at, t)}
                    </span>
                  </button>
                );
              })}
            </div>
          )}

          {/* Footer — Mark all as read */}
          {displayItems.length > 0 && unreadCount > 0 && (
            <div className="border-t border-border-light px-4 py-2">
              <button
                onClick={handleMarkAllRead}
                disabled={markAllReadMutation.isPending}
                className="flex w-full items-center justify-center gap-1.5 rounded-lg py-1.5 text-xs font-medium text-oe-blue hover:bg-oe-blue-subtle transition-colors disabled:opacity-50"
              >
                <CheckCircle2 size={12} />
                {t('notifications.mark_all_read', { defaultValue: 'Mark all as read' })}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

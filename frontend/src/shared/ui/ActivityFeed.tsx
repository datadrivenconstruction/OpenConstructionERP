/**
 * ActivityFeed — vertical timeline of recent actions across all modules.
 *
 * Queries GET /api/v1/activity?project_id=X&limit=N and renders a
 * chronological list of user actions. Each item is clickable and
 * navigates to the relevant entity.
 *
 * Usage:
 *   <ActivityFeed projectId="..." limit={15} />
 *   <ActivityFeed />  // all projects
 */

import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  FolderOpen,
  Table2,
  FileText,
  HelpCircle,
  CheckSquare,
  Database,
  CalendarDays,
  ClipboardList,
  AlertTriangle,
  ShieldCheck,
  Send,
  GitBranch,
  ShoppingCart,
  Activity,
  Receipt,
  Users,
  type LucideIcon,
} from 'lucide-react';
import clsx from 'clsx';
import { apiGet } from '@/shared/lib/api';

// ── Types ────────────────────────────────────────────────────────────────

interface ActivityEntry {
  type: string;
  entity_type: string;
  entity_id: string | null;
  title: string;
  action: string;
  user_id: string | null;
  user_name: string;
  timestamp: string | null;
  url: string;
  icon: string;
  details: Record<string, unknown>;
}

export interface ActivityFeedProps {
  /** Filter to a specific project. Omit for all projects. */
  projectId?: string;
  /** Maximum entries to show. Default 15. */
  limit?: number;
  /** Additional CSS classes. */
  className?: string;
}

// ── Icon map ─────────────────────────────────────────────────────────────

const ICON_MAP: Record<string, LucideIcon> = {
  folder: FolderOpen,
  table: Table2,
  list: Table2,
  file: FileText,
  'file-text': FileText,
  'help-circle': HelpCircle,
  'check-square': CheckSquare,
  database: Database,
  calendar: CalendarDays,
  clipboard: ClipboardList,
  'alert-triangle': AlertTriangle,
  shield: ShieldCheck,
  send: Send,
  'git-branch': GitBranch,
  'shopping-cart': ShoppingCart,
  receipt: Receipt,
  users: Users,
  activity: Activity,
};

// ── Action color map ─────────────────────────────────────────────────────

function getActionColor(action: string): string {
  if (action === 'create' || action === 'approve' || action === 'enable') {
    return 'text-semantic-success';
  }
  if (action === 'delete' || action === 'reject' || action === 'disable') {
    return 'text-semantic-error';
  }
  if (action === 'update' || action === 'export' || action === 'import') {
    return 'text-oe-blue';
  }
  return 'text-content-tertiary';
}

// ── Time formatting ──────────────────────────────────────────────────────

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

// ── Component ────────────────────────────────────────────────────────────

export function ActivityFeed({ projectId, limit = 15, className }: ActivityFeedProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const queryParams = new URLSearchParams();
  queryParams.set('limit', String(limit));
  if (projectId) queryParams.set('project_id', projectId);

  const { data: entries, isLoading } = useQuery({
    queryKey: ['activity-feed', projectId, limit],
    queryFn: () => apiGet<ActivityEntry[]>(`/v1/activity?${queryParams.toString()}`),
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: false,
  });

  const handleClick = useCallback(
    (entry: ActivityEntry) => {
      if (entry.url) {
        navigate(entry.url);
      }
    },
    [navigate],
  );

  if (isLoading) {
    return (
      <div className={clsx('space-y-3', className)}>
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex items-start gap-3 animate-pulse">
            <div className="w-7 h-7 rounded-full bg-surface-secondary shrink-0" />
            <div className="flex-1 space-y-1.5">
              <div className="h-3 w-3/4 rounded bg-surface-secondary" />
              <div className="h-2.5 w-1/3 rounded bg-surface-secondary" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  const items = entries ?? [];

  if (items.length === 0) {
    return (
      <div className={clsx('text-center py-8', className)}>
        <Activity size={24} className="mx-auto mb-2 text-content-quaternary" />
        <p className="text-xs text-content-tertiary">
          {t('activity.no_activity', { defaultValue: 'No recent activity' })}
        </p>
      </div>
    );
  }

  return (
    <div className={clsx('space-y-0.5', className)}>
      {items.map((entry, idx) => {
        const IconComponent = ICON_MAP[entry.icon] ?? Activity;
        const actionColor = getActionColor(entry.action);

        return (
          <button
            key={`${entry.entity_type}-${entry.entity_id}-${idx}`}
            type="button"
            onClick={() => handleClick(entry)}
            className={clsx(
              'flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left',
              'hover:bg-surface-secondary transition-colors group',
            )}
          >
            {/* Icon */}
            <div
              className={clsx(
                'flex h-7 w-7 shrink-0 items-center justify-center rounded-full',
                'bg-surface-secondary group-hover:bg-surface-tertiary',
                'transition-colors',
              )}
            >
              <IconComponent size={14} className={actionColor} />
            </div>

            {/* Content */}
            <div className="min-w-0 flex-1">
              <p className="text-xs text-content-primary leading-snug line-clamp-2">
                {entry.title}
              </p>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-2xs text-content-tertiary truncate">
                  {entry.user_name}
                </span>
                {entry.timestamp && (
                  <>
                    <span className="text-2xs text-content-quaternary">·</span>
                    <span className="text-2xs text-content-quaternary whitespace-nowrap">
                      {formatTimeAgo(entry.timestamp, t)}
                    </span>
                  </>
                )}
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

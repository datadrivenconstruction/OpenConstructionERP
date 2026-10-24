// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Small counts beside menu rows: "Invoices: 3 awaiting", "Issues: 5 open",
 * "Tender: due tomorrow".
 *
 * One request (`GET /v1/dashboard/nav-badges/`) feeds every badge, scoped to
 * the active project when there is one. It is polled once a minute and not
 * while the tab is hidden. The sidebar renders `<NavItemBadge itemId={item.to} />`
 * in each row; rows without a badge render nothing. `useNavItemShortcut(item.to)`
 * gives the row's palette shortcut for its tooltip ("G B"), or '' when it has none.
 */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import clsx from 'clsx';
import { apiGet } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { navActionId } from '@/app/actions/coreActions';
import { useBindings } from '@/shared/lib/actions/useActionRunner';
import { formatShortcut } from '@/shared/lib/actions/shortcuts';

export const NAV_BADGE_POLL_MS = 60_000;

export type NavBadgeKind = 'awaiting' | 'open' | 'assigned' | 'due';
export type NavBadgeTone = 'neutral' | 'warning' | 'danger';

export interface NavBadgeData {
  count: number;
  kind: NavBadgeKind;
  tone: NavBadgeTone;
  due_in_days?: number;
}

export interface NavBadgesResponse {
  project_id: string | null;
  badges: Record<string, NavBadgeData>;
}

export function navBadgesQueryKey(projectId: string | null): readonly unknown[] {
  return ['nav-badges', projectId ?? 'all'];
}

export function fetchNavBadges(projectId: string | null): Promise<NavBadgesResponse> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  return apiGet<NavBadgesResponse>(`/v1/dashboard/nav-badges/${qs}`);
}

/** All badges for the current user / active project; polled, paused while the tab is hidden. */
export function useNavBadges() {
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const signedIn = useAuthStore((s) => s.isAuthenticated || !!s.accessToken);
  return useQuery({
    queryKey: navBadgesQueryKey(projectId),
    queryFn: () => fetchNavBadges(projectId),
    enabled: signedIn,
    refetchInterval: NAV_BADGE_POLL_MS,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    staleTime: NAV_BADGE_POLL_MS / 2,
    retry: false,
  });
}

/** The badge of one menu row (its `to` path), or undefined. */
export function useNavBadge(itemId: string): NavBadgeData | undefined {
  const { data } = useNavBadges();
  return data?.badges?.[itemId];
}

/** Short visible text: the count, or "today" / "tomorrow" style for due tenders. */
export function badgeText(badge: NavBadgeData, t: TFunction): string {
  const n = badge.count > 99 ? '99+' : String(badge.count);
  if (badge.kind === 'due' && badge.due_in_days === 0) return t('nav_badges.due_today_short', { defaultValue: 'today' });
  if (badge.kind === 'due' && badge.due_in_days === 1)
    return t('nav_badges.due_tomorrow_short', { defaultValue: 'tomorrow' });
  return n;
}

/** Full sentence for the tooltip and screen readers. */
export function badgeLabel(badge: NavBadgeData, t: TFunction): string {
  const count = badge.count;
  switch (badge.kind) {
    case 'awaiting':
      return t('nav_badges.awaiting', { defaultValue: 'Awaiting approval: {{count}}', count });
    case 'assigned':
      return t('nav_badges.assigned', { defaultValue: 'Assigned to you: {{count}}', count });
    case 'due':
      if (badge.due_in_days === 0) return t('nav_badges.due_today', { defaultValue: 'Due today: {{count}}', count });
      if (badge.due_in_days === 1)
        return t('nav_badges.due_tomorrow', { defaultValue: 'Due tomorrow: {{count}}', count });
      return t('nav_badges.due_soon', { defaultValue: 'Due within two days: {{count}}', count });
    default:
      return t('nav_badges.open', { defaultValue: 'Open: {{count}}', count });
  }
}

const TONE_CLASS: Record<NavBadgeTone, string> = {
  neutral: 'bg-surface-secondary text-content-secondary border-border-light',
  warning: 'bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30',
  danger: 'bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/30',
};

/** What the Sidebar renders in a row's badge slot. Nothing when the row has no count. */
export function NavItemBadge({ itemId, className }: { itemId: string; className?: string }) {
  const { t } = useTranslation();
  const badge = useNavBadge(itemId);
  if (!badge || badge.count <= 0) return null;
  const label = badgeLabel(badge, t);
  return (
    <span
      className={clsx(
        'ms-auto inline-flex h-4 min-w-[1rem] shrink-0 items-center justify-center rounded-full border px-1',
        'text-[10px] font-semibold leading-none tabular-nums',
        TONE_CLASS[badge.tone] ?? TONE_CLASS.neutral,
        className,
      )}
      title={label}
      aria-label={label}
      data-testid={`nav-badge-${itemId}`}
    >
      {badgeText(badge, t)}
    </span>
  );
}

/** The shortcut of a menu row as people read it ("G B", "Ctrl+Alt+D"), or '' when it has none. */
export function useNavItemShortcut(itemId: string): string {
  const bindings = useBindings();
  const sc = bindings.get(navActionId(itemId));
  return sc ? formatShortcut(sc) : '';
}

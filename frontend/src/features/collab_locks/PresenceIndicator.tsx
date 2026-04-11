/**
 * PresenceIndicator — compact "who is editing" badge for any entity.
 *
 * Intended to be placed next to an entity title (BOQ name, Requirement
 * header, RFI title, ...).  Reads the live lock state via the
 * presence WebSocket hook and renders a small coloured pill:
 *
 * * Green — "You are editing"
 * * Amber — "Locked by {name} ({remaining}s)"
 * * Hidden — nobody holds a lock
 *
 * The component does NOT try to acquire the lock itself.  Pair it
 * with useEntityLock in the parent component if you want the
 * indicator to reflect the current user's own acquire state.
 */

import { useMemo } from 'react';

import { useTranslation } from '@/app/i18n';
import { useAuthStore } from '@/stores/useAuthStore';

import { usePresenceWebSocket } from './usePresenceWebSocket';
import type { CollabLock } from './api';

export interface PresenceIndicatorProps {
  entityType: string;
  entityId: string | null;
  /**
   * Optional: if the parent already holds (or is trying to acquire) a
   * lock via useEntityLock, pass it in so the indicator does not
   * flicker between "free" and "held" during the acquire round-trip.
   */
  currentLock?: CollabLock | null;
  /** Hide the whole component when no one is present.  Defaults to true. */
  hideWhenIdle?: boolean;
}

export function PresenceIndicator({
  entityType,
  entityId,
  currentLock,
  hideWhenIdle = true,
}: PresenceIndicatorProps): JSX.Element | null {
  const { t } = useTranslation();
  const { users, lastEvent } = usePresenceWebSocket(entityType, entityId);
  const userEmail = useAuthStore((s) => s.userEmail);

  // Derive the live lock holder from either the parent's lock prop
  // or the latest WebSocket snapshot.
  const holder = useMemo(() => {
    if (currentLock) {
      return {
        user_id: currentLock.user_id,
        user_name: currentLock.user_name,
        remaining_seconds: currentLock.remaining_seconds,
      };
    }
    if (lastEvent?.event === 'presence_snapshot' && lastEvent.lock) {
      return {
        user_id: lastEvent.lock.user_id,
        user_name: lastEvent.lock.user_name,
        remaining_seconds: lastEvent.lock.remaining_seconds,
      };
    }
    return null;
  }, [currentLock, lastEvent]);

  const iAmHolder = useMemo(() => {
    if (holder === null) return false;
    // Best-effort: match on email because the frontend auth store
    // does not expose the user id directly.  Works for the common
    // case where full_name === email or the holder's display string
    // contains the email.  A precise match requires a future change
    // to the auth store to persist the user id alongside the token.
    return Boolean(
      userEmail &&
        (holder.user_name === userEmail ||
          holder.user_name.includes(userEmail)),
    );
  }, [holder, userEmail]);

  if (holder === null) {
    if (hideWhenIdle) return null;
    if (users.length === 0) return null;
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900/40 dark:text-blue-200"
        title={t('collab_locks.viewers_tooltip', {
          defaultValue: '{{count}} people viewing',
          count: users.length,
        })}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-blue-500" />
        {t('collab_locks.viewers_label', {
          defaultValue: '{{count}} viewing',
          count: users.length,
        })}
      </span>
    );
  }

  if (iAmHolder) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-200">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
        {t('collab_locks.lock_held_by_you', {
          defaultValue: 'You are editing',
        })}
      </span>
    );
  }

  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-200"
      title={t('collab_locks.lock_held_by_other_tooltip', {
        defaultValue: 'Locked by {{name}} — {{seconds}}s remaining',
        name: holder.user_name,
        seconds: holder.remaining_seconds,
      })}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
      {t('collab_locks.lock_held_by_other', {
        defaultValue: 'Locked by {{name}}',
        name: holder.user_name,
      })}
    </span>
  );
}

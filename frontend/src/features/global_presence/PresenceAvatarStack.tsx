// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * PresenceAvatarStack -- shows small circular avatars for online users.
 *
 * Reads from `useGlobalPresenceStore`, filters out the current user, and
 * renders up to 5 initials-based avatars with an optional "+N" overflow
 * pill. Active users get a green dot; idle users are dimmed.
 *
 * Click on any avatar opens a `PresenceTooltip` popover with details.
 */

import { useState, useRef, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

import { useAuthStore } from '@/stores/useAuthStore';
import { useGlobalPresenceStore } from '@/stores/useGlobalPresenceStore';
import type { GlobalPresenceUser } from '@/stores/useGlobalPresenceStore';
import { PresenceTooltip } from './PresenceTooltip';

/* ── Helpers ───────────────────────────────────────────────────────── */

/** Maximum number of avatars shown before the overflow pill. */
const MAX_VISIBLE = 5;

/** Deterministic color palette for user avatars. */
const AVATAR_COLORS = [
  'bg-blue-500',
  'bg-emerald-500',
  'bg-amber-500',
  'bg-violet-500',
  'bg-rose-500',
  'bg-cyan-500',
  'bg-orange-500',
  'bg-indigo-500',
];

function avatarColor(userId: string): string {
  let hash = 0;
  for (let i = 0; i < userId.length; i++) {
    hash = ((hash << 5) - hash + userId.charCodeAt(i)) | 0;
  }
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length]!;
}

function avatarInitials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length >= 2) {
    return (parts[0]![0]! + parts[parts.length - 1]![0]!).toUpperCase();
  }
  return (name.trim()[0] ?? 'U').toUpperCase();
}

/**
 * Decode the `sub` (user id) claim from a JWT access token.
 *
 * The backend `CurrentUserId` reads the same claim, so matching against
 * it client-side filters the current user from the presence roster.
 * Returns `null` on any decoding error.
 */
function decodeUserIdFromToken(token: string | null): string | null {
  if (!token) return null;
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = parts[1]!.replace(/-/g, '+').replace(/_/g, '/');
    const padded = payload + '='.repeat((4 - (payload.length % 4)) % 4);
    const json = JSON.parse(atob(padded)) as { sub?: string };
    return typeof json.sub === 'string' ? json.sub : null;
  } catch {
    return null;
  }
}

/* ── Component ─────────────────────────────────────────────────────── */

export function PresenceAvatarStack() {
  const { t } = useTranslation();
  const users = useGlobalPresenceStore((s) => s.users);
  const wsStatus = useGlobalPresenceStore((s) => s.wsStatus);
  const accessToken = useAuthStore((s) => s.accessToken);

  const currentUserId = useMemo(
    () => decodeUserIdFromToken(accessToken),
    [accessToken],
  );

  const [openUserId, setOpenUserId] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const otherUsers = useMemo(() => {
    const all = Object.values(users);
    if (currentUserId) {
      return all.filter((u) => u.user_id !== currentUserId);
    }
    return all;
  }, [users, currentUserId]);

  const visibleUsers = otherUsers.slice(0, MAX_VISIBLE);
  const overflowCount = otherUsers.length - MAX_VISIBLE;

  const handleAvatarClick = useCallback((userId: string) => {
    setOpenUserId((prev) => (prev === userId ? null : userId));
  }, []);

  const closeTooltip = useCallback(() => setOpenUserId(null), []);

  // Nothing to show if no other users or WS never connected.
  if (wsStatus !== 'open' || otherUsers.length === 0) {
    return null;
  }

  const openUser = openUserId ? users[openUserId] ?? null : null;

  return (
    <div
      ref={containerRef}
      className="hidden sm:flex items-center gap-0.5 relative"
    >
      {visibleUsers.map((user) => (
        <AvatarButton
          key={user.user_id}
          user={user}
          isOpen={openUserId === user.user_id}
          onClick={() => handleAvatarClick(user.user_id)}
        />
      ))}

      {overflowCount > 0 && (
        <span
          className={clsx(
            'flex h-7 items-center justify-center rounded-full px-1.5',
            'bg-surface-secondary text-[10px] font-semibold text-content-tertiary',
            'select-none',
          )}
          title={t('presence.more_users', {
            defaultValue: '+{{count}} more',
            count: overflowCount,
          })}
        >
          +{overflowCount}
        </span>
      )}

      {openUser && (
        <PresenceTooltip user={openUser} onClose={closeTooltip} />
      )}
    </div>
  );
}

/* ── Avatar button ─────────────────────────────────────────────────── */

interface AvatarButtonProps {
  user: GlobalPresenceUser;
  isOpen: boolean;
  onClick: () => void;
}

function AvatarButton({ user, isOpen, onClick }: AvatarButtonProps) {
  const isIdle = user.status === 'idle';
  const initials = avatarInitials(user.user_name);
  const color = avatarColor(user.user_id);

  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={user.user_name}
      className={clsx(
        'relative flex h-7 w-7 items-center justify-center rounded-full',
        'text-[10px] font-semibold text-white',
        'ring-2 ring-surface-primary',
        'transition-opacity duration-fast ease-oe',
        color,
        isIdle && 'opacity-50',
        isOpen && 'ring-oe-blue',
      )}
    >
      {initials}
      {/* Status dot */}
      <span
        className={clsx(
          'absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full',
          'border-2 border-surface-primary',
          isIdle ? 'bg-content-quaternary' : 'bg-emerald-500',
        )}
      />
    </button>
  );
}

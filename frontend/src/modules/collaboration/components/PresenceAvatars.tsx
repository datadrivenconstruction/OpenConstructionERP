/**
 * Tiny avatar stack showing users currently viewing a BOQ.
 * Renders max 3 avatars + "+N" overflow badge.
 */
import { useMemo } from 'react';
import { usePresenceStore, type PresenceUser } from '../hooks/usePresence';

const MAX_VISIBLE = 3;

export function PresenceAvatars({ boqId }: { boqId: string }) {
  // Select raw data (stable reference) and derive filtered list in useMemo
  // to avoid infinite re-render from getUsersForBOQ creating new arrays
  const remoteUsers = usePresenceStore((s) => s.remoteUsers);
  const users = useMemo(
    () => Object.values(remoteUsers).filter((u) => u.boqId === boqId),
    [remoteUsers, boqId],
  );
  if (users.length === 0) return null;

  const visible = users.slice(0, MAX_VISIBLE);
  const overflow = users.length - MAX_VISIBLE;

  return (
    <div className="flex items-center -space-x-1.5" title={users.map((u) => u.name).join(', ')}>
      {visible.map((u) => (
        <Avatar key={u.id} user={u} />
      ))}
      {overflow > 0 && (
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-surface-tertiary text-2xs font-bold text-content-secondary ring-2 ring-surface-primary z-10">
          +{overflow}
        </span>
      )}
    </div>
  );
}

function Avatar({ user }: { user: PresenceUser }) {
  const initial = user.name.charAt(0).toUpperCase();
  return (
    <span
      className="flex h-5 w-5 items-center justify-center rounded-full text-2xs font-bold text-white ring-2 ring-surface-primary"
      style={{ backgroundColor: user.color }}
      title={user.name}
    >
      {initial}
    </span>
  );
}

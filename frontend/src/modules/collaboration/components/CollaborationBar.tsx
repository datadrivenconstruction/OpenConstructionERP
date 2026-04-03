import { useTranslation } from 'react-i18next';
import { Users } from 'lucide-react';
import type { CollabUser } from '../types';
import type { ConnectionStatusInfo } from '../hooks/useConnectionStatus';
import { ConnectionStatus } from './ConnectionStatus';

interface CollaborationBarProps {
  users: CollabUser[];
  connected: boolean;
  connectionInfo?: ConnectionStatusInfo;
  onOpenShareDialog?: () => void;
}

export function CollaborationBar({
  users,
  connected,
  connectionInfo,
  onOpenShareDialog,
}: CollaborationBarProps) {
  const { t } = useTranslation();
  const remoteUsers = users.filter((u) => !u.isLocal);
  const localUser = users.find((u) => u.isLocal);

  // Build a fallback ConnectionStatusInfo from the legacy `connected` boolean
  // so the component works even when connectionInfo is not provided.
  const effectiveInfo: ConnectionStatusInfo = connectionInfo ?? {
    status: connected ? 'connected' : 'disconnected',
    peerCount: Math.max(0, users.filter((u) => !u.isLocal).length),
    lastSyncTime: null,
    secondsSinceSync: null,
  };

  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-surface-primary px-3 py-2">
      {/* Connection status indicator */}
      <ConnectionStatus connectionInfo={effectiveInfo} />

      <span className="w-px h-4 bg-border" />

      {/* User avatars */}
      <div className="flex items-center -space-x-1.5">
        {localUser && (
          <UserAvatar
            name={localUser.userName}
            color={localUser.color}
            isLocal
          />
        )}
        {remoteUsers.map((u) => (
          <UserAvatar
            key={u.userId}
            name={u.userName}
            color={u.color}
          />
        ))}
      </div>

      <span className="text-xs text-content-secondary">
        <Users size={12} className="inline mr-1" />
        {users.length} {t('collab.online', { defaultValue: 'online' })}
      </span>

      {/* Share button */}
      {onOpenShareDialog && (
        <button
          onClick={onOpenShareDialog}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1 text-xs font-medium text-white hover:bg-oe-blue-hover transition-colors"
        >
          {t('collab.share', { defaultValue: 'Share' })}
        </button>
      )}
    </div>
  );
}

function UserAvatar({
  name,
  color,
  isLocal = false,
}: {
  name: string;
  color: string;
  isLocal?: boolean;
}) {
  const initials = name
    .split(' ')
    .map((w) => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);

  return (
    <div
      className="relative flex h-7 w-7 items-center justify-center rounded-full border-2 border-surface-primary text-[10px] font-bold text-white"
      style={{ backgroundColor: color }}
      title={`${name}${isLocal ? ' (you)' : ''}`}
    >
      {initials || '?'}
      {isLocal && (
        <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-emerald-400 border border-surface-primary" />
      )}
    </div>
  );
}

import { useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import type { ConnectionStatusInfo } from '../hooks/useConnectionStatus';

interface ConnectionStatusProps {
  connectionInfo: ConnectionStatusInfo;
}

/**
 * Compact connection status indicator with colored dot, status text, and peer count.
 * Shows full details (including last sync time) on hover via a tooltip.
 */
export function ConnectionStatus({ connectionInfo }: ConnectionStatusProps) {
  const { t } = useTranslation();
  const { status, peerCount, secondsSinceSync } = connectionInfo;
  const [showTooltip, setShowTooltip] = useState(false);
  const tooltipTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const dotColor =
    status === 'connected'
      ? 'bg-emerald-500'
      : status === 'connecting'
        ? 'bg-amber-400'
        : 'bg-red-500';

  const dotPulse = status === 'connecting' ? 'animate-pulse' : '';

  const statusLabel =
    status === 'connected'
      ? t('collab.connected', { defaultValue: 'Connected' })
      : status === 'connecting'
        ? t('collab.connecting', { defaultValue: 'Connecting...' })
        : t('collab.disconnected', { defaultValue: 'Disconnected' });

  const peersUnit = t('collab.peers_unit', { defaultValue: 'peers' });
  const peerLabel = `${peerCount} ${peersUnit}`;

  const syncLabel = formatSyncLabel(secondsSinceSync, t);

  const handleMouseEnter = () => {
    if (tooltipTimeout.current) clearTimeout(tooltipTimeout.current);
    setShowTooltip(true);
  };

  const handleMouseLeave = () => {
    tooltipTimeout.current = setTimeout(() => setShowTooltip(false), 150);
  };

  return (
    <div
      className="relative flex items-center gap-1.5 cursor-default"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {/* Colored dot */}
      <span className={`inline-block h-2 w-2 rounded-full ${dotColor} ${dotPulse}`} />

      {/* Compact: peer count */}
      <span className="text-xs text-content-secondary whitespace-nowrap">{peerLabel}</span>

      {/* Tooltip on hover */}
      {showTooltip && (
        <div className="absolute left-1/2 -translate-x-1/2 top-full mt-2 z-50 min-w-[160px] rounded-lg border border-border bg-surface-elevated px-3 py-2 shadow-lg">
          <div className="flex items-center gap-1.5 mb-1">
            <span className={`inline-block h-2 w-2 rounded-full ${dotColor}`} />
            <span className="text-xs font-medium text-content-primary">{statusLabel}</span>
          </div>
          <p className="text-2xs text-content-tertiary">{peerLabel}</p>
          {syncLabel && <p className="text-2xs text-content-tertiary mt-0.5">{syncLabel}</p>}
          {/* Small arrow pointing up */}
          <div className="absolute left-1/2 -translate-x-1/2 -top-1 h-2 w-2 rotate-45 border-l border-t border-border bg-surface-elevated" />
        </div>
      )}
    </div>
  );
}

/**
 * Format seconds since last sync into a human-readable label.
 */
function formatSyncLabel(
  seconds: number | null,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string | null {
  if (seconds === null) return null;

  const syncedPrefix = t('collab.synced_prefix', { defaultValue: 'Synced' });

  if (seconds < 5) {
    const justNow = t('collab.just_now', { defaultValue: 'just now' });
    return `${syncedPrefix} ${justNow}`;
  }
  if (seconds < 60) {
    const agoSuffix = t('collab.ago', { defaultValue: 'ago' });
    return `${syncedPrefix} ${seconds}s ${agoSuffix}`;
  }
  const minutes = Math.floor(seconds / 60);
  const agoSuffix = t('collab.ago', { defaultValue: 'ago' });
  return `${syncedPrefix} ${minutes}m ${agoSuffix}`;
}

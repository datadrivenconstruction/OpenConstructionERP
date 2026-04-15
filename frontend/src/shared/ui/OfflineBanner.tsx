import { useTranslation } from 'react-i18next';
import { WifiOff, RefreshCw } from 'lucide-react';
import { useOnlineStatus } from '../hooks/useOnlineStatus';
import { useState, useEffect } from 'react';
import { getQueuedMutations } from '../lib/offlineStore';

/**
 * Banner shown at the top of the page when the user loses network connectivity.
 * When offline, displays an informational message about local data storage.
 * Displays pending mutation count and auto-hides when back online.
 */
export function OfflineBanner() {
  const { t } = useTranslation();
  const isOnline = useOnlineStatus();
  const [pendingCount, setPendingCount] = useState(0);
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (!isOnline) {
      setShow(true);
      // Check pending mutation count
      getQueuedMutations().then((q) => setPendingCount(q.length));
    } else {
      // Fade out after reconnecting
      const timer = setTimeout(() => setShow(false), 2000);
      return () => clearTimeout(timer);
    }
  }, [isOnline]);

  if (!show) return null;

  return (
    <div
      role="status"
      data-testid="offline-banner"
      className={`flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium transition-all duration-300 ${
        isOnline
          ? 'bg-semantic-success-bg text-semantic-success'
          : 'bg-blue-50 text-blue-700 dark:bg-blue-950/30 dark:text-blue-300'
      }`}
    >
      {isOnline ? (
        <>
          <RefreshCw className="h-4 w-4 animate-spin" />
          {t('offline.reconnected', { defaultValue: 'Back online — syncing changes...' })}
        </>
      ) : (
        <>
          <WifiOff className="h-4 w-4" />
          {t('offline.banner', { defaultValue: 'No network connection. All data is stored locally on your device.' })}
          {pendingCount > 0 && (
            <span className="ml-1 rounded-full bg-blue-200/40 dark:bg-blue-800/40 px-2 py-0.5 text-xs">
              {t('offline.pending_count', {
                defaultValue: '{{count}} pending',
                count: pendingCount,
              })}
            </span>
          )}
        </>
      )}
    </div>
  );
}

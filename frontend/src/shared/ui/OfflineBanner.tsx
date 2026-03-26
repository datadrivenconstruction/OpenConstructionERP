import { useTranslation } from 'react-i18next';
import { WifiOff, RefreshCw } from 'lucide-react';
import { useOnlineStatus } from '../hooks/useOnlineStatus';
import { useState, useEffect } from 'react';
import { getQueuedMutations } from '../lib/offlineStore';

/**
 * Banner shown at the top of the page when the user is offline.
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
      role="alert"
      data-testid="offline-banner"
      className={`flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium transition-all duration-300 ${
        isOnline
          ? 'bg-semantic-success-bg text-semantic-success'
          : 'bg-semantic-warning-bg text-semantic-warning'
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
          {t('offline.banner', { defaultValue: 'You are offline. Changes will be saved locally.' })}
          {pendingCount > 0 && (
            <span className="ml-1 rounded-full bg-semantic-warning/20 px-2 py-0.5 text-xs">
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

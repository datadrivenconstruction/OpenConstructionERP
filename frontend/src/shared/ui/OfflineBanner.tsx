// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { WifiOff, X } from 'lucide-react';
import { useOnlineStatus } from '@/shared/hooks/useOnlineStatus';
import { isTauri } from '@/shared/lib/desktop';

const SESSION_DISMISS_KEY = 'oe_offline_banner_dismissed_session';

/**
 * Top-of-app banner surfaced whenever the browser reports `navigator.onLine = false`.
 * Auto-hides on reconnect; user can dismiss for the current tab session via the
 * close button (sessionStorage scoped so a fresh tab brings it back).
 *
 * The copy is context-aware. In the desktop (Tauri) build the backend is a local
 * sidecar (embedded PostgreSQL) that stays reachable with or without internet, so a
 * dropped connection never means lost data - the message reassures that work is saved
 * locally and only live multi-user collaboration is paused. In the web/PWA build the
 * server genuinely is remote, so the plain "changes will not sync" wording stands.
 */
export function OfflineBanner() {
  const { t } = useTranslation();
  const isOnline = useOnlineStatus();
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return sessionStorage.getItem(SESSION_DISMISS_KEY) === '1';
    } catch {
      return false;
    }
  });

  // Coming back online clears the dismissal so the next disconnect surfaces it again
  useEffect(() => {
    if (isOnline) {
      try { sessionStorage.removeItem(SESSION_DISMISS_KEY); } catch { /* ignore */ }
      setDismissed(false);
    }
  }, [isOnline]);

  if (isOnline || dismissed) return null;

  const handleDismiss = () => {
    try { sessionStorage.setItem(SESSION_DISMISS_KEY, '1'); } catch { /* ignore */ }
    setDismissed(true);
  };

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="offline-banner"
      className="oe-dock-aware sticky top-0 z-50 flex items-center justify-center gap-2 bg-amber-500/95 px-4 py-2 text-[13px] font-medium text-white shadow-sm backdrop-blur-sm"
    >
      <WifiOff size={14} strokeWidth={2.25} className="shrink-0" />
      <span className="text-center">
        {isTauri
          ? t('common.offline_banner_desktop', {
              defaultValue:
                "You're offline. Your work is saved on this computer - only live multi-user collaboration pauses until you reconnect.",
            })
          : t('common.offline_banner', {
              defaultValue: "You're offline - changes will not sync.",
            })}
      </span>
      <button
        type="button"
        onClick={handleDismiss}
        aria-label={t('common.dismiss', { defaultValue: 'Dismiss' })}
        className="ml-2 flex h-5 w-5 items-center justify-center rounded text-white/80 hover:bg-white/15 hover:text-white transition-colors"
      >
        <X size={12} />
      </button>
    </div>
  );
}

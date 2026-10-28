// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * OfflineFallback — minimal full-page "you're offline" screen.
 *
 * Intended to be referenced from the workbox NavigationRoute as the
 * offline fallback document.  Also exported directly so feature pages
 * can render it inline when their primary data hook fails with a
 * network error and ``navigator.onLine`` is false.
 *
 * Surfaces a best-effort "last synced N minutes ago" line built from
 * a localStorage timestamp the rest of the app can update via the
 * exported ``markLastSync()`` helper (no-op when localStorage is
 * unavailable).
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CloudOff } from 'lucide-react';

const LAST_SYNC_KEY = 'oce.pwa.lastSyncAt';

/**
 * Persist the moment of a successful network round-trip. Feature
 * data hooks that confirm a fresh response can call this so the
 * offline screen displays an accurate "last synced" hint.
 */
export function markLastSync(): void {
  try {
    localStorage.setItem(LAST_SYNC_KEY, new Date().toISOString());
  } catch {
    // localStorage unavailable — ignore, "last synced" line will just be hidden.
  }
}

function formatRelative(iso: string | null, locale: string): string | null {
  if (!iso) return null;
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return null;
  const deltaMs = Date.now() - ts;
  const deltaMin = Math.max(0, Math.round(deltaMs / 60_000));

  // Prefer Intl.RelativeTimeFormat when available for proper plurals/i18n.
  try {
    const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
    if (deltaMin < 60) return rtf.format(-deltaMin, 'minute');
    const deltaH = Math.round(deltaMin / 60);
    if (deltaH < 24) return rtf.format(-deltaH, 'hour');
    const deltaD = Math.round(deltaH / 24);
    return rtf.format(-deltaD, 'day');
  } catch {
    return `${deltaMin} min ago`;
  }
}

export function OfflineFallback() {
  const { t, i18n } = useTranslation();
  const [lastSyncLabel, setLastSyncLabel] = useState<string | null>(null);

  useEffect(() => {
    try {
      setLastSyncLabel(formatRelative(localStorage.getItem(LAST_SYNC_KEY), i18n.language || 'en'));
    } catch {
      setLastSyncLabel(null);
    }
  }, [i18n.language]);

  return (
    <div
      role="alert"
      data-testid="offline-fallback"
      className="flex min-h-[60vh] flex-col items-center justify-center gap-4 px-6 py-12 text-center"
    >
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-amber-100 text-amber-700">
        <CloudOff size={28} strokeWidth={1.75} />
      </div>
      <h1 className="text-xl font-semibold text-content-primary">
        {t('pwa.offline_title', { defaultValue: "You're offline" })}
      </h1>
      <p className="max-w-md text-sm text-content-secondary">
        {t('pwa.offline_body', {
          defaultValue:
            'OCERP can\'t reach the server right now. Cached pages remain available; any changes you make will need to be re-saved once you reconnect.',
        })}
      </p>
      {lastSyncLabel && (
        <p className="text-xs text-content-tertiary">
          {t('pwa.last_synced', { defaultValue: 'Last synced {{when}}', when: lastSyncLabel })}
        </p>
      )}
    </div>
  );
}

export default OfflineFallback;

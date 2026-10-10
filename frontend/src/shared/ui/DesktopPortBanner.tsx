// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Info, X } from 'lucide-react';
import { isTauri } from '@/shared/lib/desktop';

/** The port the desktop app normally serves on (DEFAULT_BACKEND_PORT in the launcher). */
export const DESKTOP_DEFAULT_PORT = '8732';

const SEEN_KEY = 'oe_desktop_port_banner_seen';

/**
 * The port the desktop window was moved to, or `null` when it is where it
 * normally is (or this is not the desktop window at all).
 *
 * Only a window on this computer counts: a desktop app pointed at a server
 * elsewhere is served from that server's address, and its port says nothing
 * about another program on this computer.
 */
export function movedDesktopPort(
  desktop: boolean,
  location: Pick<Location, 'hostname' | 'port'>,
): string | null {
  if (!desktop) return null;
  if (location.hostname !== '127.0.0.1' && location.hostname !== 'localhost') return null;
  if (!location.port || location.port === DESKTOP_DEFAULT_PORT) return null;
  return location.port;
}

/**
 * Says once why the desktop window may have signed the user out and lost the
 * language: another program held port 8732, so the app opened on another
 * port, and the browser keeps sign-in and language per port.
 *
 * "Once" is per port, which is exactly the scope of the loss: the flag is kept
 * in the same per-origin storage that was found empty, so each port the window
 * lands on explains itself the first time and never again.
 */
export function DesktopPortBanner() {
  const { t } = useTranslation();
  const [port] = useState(() =>
    typeof window === 'undefined' ? null : movedDesktopPort(isTauri, window.location),
  );
  const [seen, setSeen] = useState<boolean>(() => {
    try {
      return localStorage.getItem(SEEN_KEY) === '1';
    } catch {
      return false;
    }
  });

  if (!port || seen) return null;

  const handleDismiss = () => {
    try { localStorage.setItem(SEEN_KEY, '1'); } catch { /* ignore */ }
    setSeen(true);
  };

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="desktop-port-banner"
      className="oe-dock-aware sticky top-0 z-50 flex items-center justify-center gap-2 bg-oe-blue px-4 py-2 text-[13px] font-medium text-white shadow-sm"
    >
      <Info size={14} strokeWidth={2.25} className="shrink-0" />
      <span className="text-center">
        {t('common.desktop_port_moved', {
          port,
          defaultPort: DESKTOP_DEFAULT_PORT,
          defaultValue:
            'Another program is using port {{defaultPort}}, so the app opened on port {{port}}. Sign-in and language are kept per port, so you may need to sign in or pick your language again once. Your projects and data are not affected.',
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

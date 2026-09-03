// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Presence beacon - tells the Team Standup metrics where a signed-in
// person is in the ERP. Mounted ONCE in the app shell; renders nothing.
//
// Rules, all client-side (the server caps each ping regardless):
//   * ping every PING_MS while the tab is visible, and on every route
//     change (closing the slot for the path being left);
//   * the seconds sent are wall-clock seconds since the last ping,
//     never more than the server cap, never while the tab was hidden;
//   * no mouse / key / scroll for IDLE_MS -> stop pinging until activity
//     (the minute that ended in idleness is still reported once);
//   * pagehide -> a last ping for the open minute plus an `end` session
//     event (keepalive), so attendance knows when the tab went away;
//   * every failure is silent - a beacon has no right to a toast.

import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';

import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

import { sendPresencePing, sendSessionEvent } from './metricsApi';

const PING_MS = 60_000;
const IDLE_MS = 5 * 60_000;
const MAX_SECONDS = 120;
const ACTIVITY_EVENTS: (keyof WindowEventMap)[] = [
  'mousemove',
  'mousedown',
  'keydown',
  'scroll',
  'touchstart',
  'pointerdown',
];

export function PresenceBeacon() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const location = useLocation();

  const lastPingAt = useRef<number>(Date.now());
  const lastActivityAt = useRef<number>(Date.now());
  const pathRef = useRef<string>(location.pathname);
  const projectRef = useRef<string | null>(activeProjectId);
  projectRef.current = activeProjectId;

  useEffect(() => {
    if (!isAuthenticated) return;

    const now = () => Date.now();
    lastPingAt.current = now();
    lastActivityAt.current = now();

    const flush = (path: string) => {
      const t = now();
      const seconds = Math.min(MAX_SECONDS, Math.max(0, Math.round((t - lastPingAt.current) / 1000)));
      lastPingAt.current = t;
      if (seconds <= 0) return;
      if (typeof navigator !== 'undefined' && navigator.onLine === false) return;
      void sendPresencePing({ path, project_id: projectRef.current, seconds });
    };

    const tick = () => {
      if (document.visibilityState !== 'visible') {
        // Nothing to claim for a hidden tab; restart the clock on return.
        lastPingAt.current = now();
        return;
      }
      const idleFor = now() - lastActivityAt.current;
      if (idleFor > IDLE_MS) {
        // Idle: report nothing; the clock restarts when activity resumes.
        lastPingAt.current = now();
        return;
      }
      flush(pathRef.current);
    };

    const onActivity = () => {
      const t = now();
      if (t - lastActivityAt.current > IDLE_MS) {
        // Coming back from idle - do not credit the idle stretch.
        lastPingAt.current = t;
      }
      lastActivityAt.current = t;
    };

    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        lastPingAt.current = now();
        lastActivityAt.current = now();
      } else {
        // Leaving: close the open minute for this path.
        flush(pathRef.current);
      }
    };

    // The tab is going away (close, navigate off, bfcache): a final ping
    // for the open minute, then an `end` so the attendance table can show
    // when they finished. Both keepalive; the server merges an `end` that
    // fires twice within a minute (pagehide + hidden on the same close).
    const onPageHide = () => {
      flush(pathRef.current);
      if (typeof navigator !== 'undefined' && navigator.onLine === false) return;
      void sendSessionEvent('end');
    };

    const timer = window.setInterval(tick, PING_MS);
    for (const ev of ACTIVITY_EVENTS) window.addEventListener(ev, onActivity, { passive: true });
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pagehide', onPageHide);
    return () => {
      window.clearInterval(timer);
      for (const ev of ACTIVITY_EVENTS) window.removeEventListener(ev, onActivity);
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pagehide', onPageHide);
    };
  }, [isAuthenticated]);

  // Route change: close the slot for the path being left, then track the new one.
  useEffect(() => {
    if (!isAuthenticated) {
      pathRef.current = location.pathname;
      return;
    }
    const previous = pathRef.current;
    if (previous !== location.pathname) {
      if (document.visibilityState === 'visible' && Date.now() - lastActivityAt.current <= IDLE_MS) {
        const seconds = Math.min(
          MAX_SECONDS,
          Math.max(0, Math.round((Date.now() - lastPingAt.current) / 1000)),
        );
        if (seconds > 0 && navigator.onLine !== false) {
          void sendPresencePing({ path: previous, project_id: projectRef.current, seconds });
        }
      }
      lastPingAt.current = Date.now();
      pathRef.current = location.pathname;
    }
  }, [isAuthenticated, location.pathname]);

  return null;
}

export default PresenceBeacon;

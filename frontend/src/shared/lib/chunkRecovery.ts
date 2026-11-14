/**
 * Stale lazy-chunk recovery, shared by the `vite:preloadError` listener and
 * the ErrorBoundary so the two paths use one loop guard.
 *
 * After an upgrade the precaching service worker can keep serving the old
 * index.html, so a plain reload would request the same vanished chunk hashes
 * again. Before reloading we drop the worker registrations and the caches so
 * the reload comes from the network.
 */

const KEY = 'oe_chunk_reload_at';
const WINDOW_MS = 10_000;

export function isChunkLoadError(message: string): boolean {
  return (
    message.includes('Failed to fetch dynamically imported module') ||
    message.includes('Importing a module script failed') ||
    /Loading chunk \d+ failed/i.test(message)
  );
}

async function dropServiceWorkerState(): Promise<void> {
  try {
    if (typeof navigator !== 'undefined' && navigator.serviceWorker?.getRegistrations) {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map((r) => r.unregister()));
    }
    if (typeof caches !== 'undefined') {
      const names = await caches.keys();
      await Promise.all(names.map((n) => caches.delete(n)));
    }
  } catch {
    // Best effort: the reload still happens.
  }
}

/**
 * Reload once per 10 s window. Returns true when a reload was started, false
 * when the guard (or unavailable storage) says the fresh build is broken too.
 */
export function recoverFromStaleChunk(now: number = Date.now()): boolean {
  try {
    const last = Number(sessionStorage.getItem(KEY) ?? '0');
    if (now - last <= WINDOW_MS) return false;
    sessionStorage.setItem(KEY, String(now));
  } catch {
    return false;
  }
  void dropServiceWorkerState().finally(() => window.location.reload());
  return true;
}

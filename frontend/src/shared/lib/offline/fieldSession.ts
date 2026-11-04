import { clearAllRefs } from './refCache';

export const FIELD_CLEAR_MESSAGE = 'oe-field-clear';
const FIELD_DATA_CACHE_PREFIX = 'oe-field-data';

/**
 * Drop per-user read data kept for offline use: the field service worker's data
 * cache and the IndexedDB reference store. The mutation queue and unsynced
 * records are NOT touched: unsent captures must survive a sign-out.
 */
export async function purgeFieldUserData(): Promise<void> {
  try {
    if (typeof caches !== 'undefined') {
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k.startsWith(FIELD_DATA_CACHE_PREFIX)).map((k) => caches.delete(k)));
    }
  } catch {
    /* cache storage unavailable */
  }
  try {
    if (typeof navigator !== 'undefined' && navigator.serviceWorker?.getRegistrations) {
      const regs = await navigator.serviceWorker.getRegistrations();
      for (const r of regs) r.active?.postMessage({ type: FIELD_CLEAR_MESSAGE });
    }
  } catch {
    /* no worker to tell */
  }
  await clearAllRefs();
}

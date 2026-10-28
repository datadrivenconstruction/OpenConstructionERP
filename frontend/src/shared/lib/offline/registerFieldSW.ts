// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Registration helper for the field PWA service worker (`public/field-sw.js`).
 *
 * Registered with `scope: '/field'` so it controls only the field shell and does
 * not collide with the app-wide workbox SW (`/sw.js`) nor with the deliberate
 * self-destruct stub checked in at `public/sw.js`. Registration is best-effort:
 * if service workers are unavailable, or registration fails, the field shell
 * still works fully because offline correctness rests on the IndexedDB mutation
 * queue, not on this worker.
 *
 * No-op in the Vite dev server (`import.meta.env.DEV`) so a stale precache never
 * shadows HMR edits, mirroring the workbox `devOptions.enabled === false`.
 */

const FIELD_SW_URL = '/field-sw.js';
const FIELD_SW_SCOPE = '/field';

export interface RegisterFieldSWResult {
  registered: boolean;
  reason?: string;
}

/**
 * Register the field service worker. Returns whether registration happened and,
 * when it did not, a short machine-readable reason for diagnostics.
 */
export async function registerFieldServiceWorker(): Promise<RegisterFieldSWResult> {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) {
    return { registered: false, reason: 'unsupported' };
  }
  // Skip in dev to avoid shadowing HMR; the production build serves the file.
  if (typeof import.meta !== 'undefined' && import.meta.env?.DEV) {
    return { registered: false, reason: 'dev' };
  }
  try {
    await navigator.serviceWorker.register(FIELD_SW_URL, { scope: FIELD_SW_SCOPE });
    return { registered: true };
  } catch (err) {
    return { registered: false, reason: err instanceof Error ? err.message : 'error' };
  }
}

/** Unregister the field service worker (used on field session sign-out). */
export async function unregisterFieldServiceWorker(): Promise<void> {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return;
  try {
    const regs = await navigator.serviceWorker.getRegistrations();
    await Promise.all(
      regs
        .filter((r) => r.scope.endsWith(FIELD_SW_SCOPE) || r.scope.endsWith(`${FIELD_SW_SCOPE}/`))
        .map((r) => r.unregister()),
    );
  } catch {
    /* ignore */
  }
}

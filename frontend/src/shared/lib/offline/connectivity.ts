// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Connectivity detection — framework-light online/offline source of truth.
 *
 * Wraps `navigator.onLine` plus the browser `online`/`offline` events behind a
 * tiny observable store so any surface (the desktop shell, the field PWA shell,
 * the mutation-queue drain loop) can subscribe to connectivity transitions
 * without pulling in a React-specific hook. A `useSyncExternalStore` adapter is
 * provided for React consumers, but the core is plain DOM + closures so it stays
 * unit-testable in jsdom without a real network stack.
 *
 * No dependencies. `navigator.onLine` is treated as advisory only (it can lie
 * behind captive portals), so callers that need a stronger signal should fall
 * back to a real request; this module just surfaces the cheap browser signal.
 */

export type ConnectivityListener = (online: boolean) => void;

/**
 * Read the browser's current connectivity hint.
 *
 * Defaults to `true` (optimistic) when `navigator` is unavailable, e.g. during
 * SSR or in a test realm that has not polyfilled it, so reads never throw.
 */
export function isOnline(): boolean {
  if (typeof navigator === 'undefined' || typeof navigator.onLine !== 'boolean') {
    return true;
  }
  return navigator.onLine;
}

const listeners = new Set<ConnectivityListener>();
let domBound = false;

function handleOnline(): void {
  emit(true);
}

function handleOffline(): void {
  emit(false);
}

function emit(online: boolean): void {
  // Snapshot to an array so a listener that unsubscribes during dispatch does
  // not mutate the set mid-iteration.
  for (const listener of [...listeners]) {
    listener(online);
  }
}

function bindDom(): void {
  if (domBound || typeof window === 'undefined' || typeof window.addEventListener !== 'function') {
    return;
  }
  window.addEventListener('online', handleOnline);
  window.addEventListener('offline', handleOffline);
  domBound = true;
}

function unbindDom(): void {
  if (!domBound || typeof window === 'undefined') {
    return;
  }
  window.removeEventListener('online', handleOnline);
  window.removeEventListener('offline', handleOffline);
  domBound = false;
}

/**
 * Subscribe to connectivity transitions. Returns an unsubscribe function.
 *
 * The DOM listeners are bound lazily on the first subscription and torn down
 * when the last subscriber leaves, so there is no leak when nothing is
 * listening.
 */
export function subscribeConnectivity(listener: ConnectivityListener): () => void {
  listeners.add(listener);
  bindDom();
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      unbindDom();
    }
  };
}

/**
 * Test-only seam: emit a synthetic connectivity transition to every subscriber.
 *
 * Production code never calls this; tests use it to drive the queue drain loop
 * without dispatching real `window` events (jsdom does fire them, but this keeps
 * the store's behaviour assertable in isolation).
 */
export function emitConnectivityForTests(online: boolean): void {
  emit(online);
}

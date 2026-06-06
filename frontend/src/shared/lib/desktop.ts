/**
 * Shared desktop (Tauri) runtime detection.
 *
 * The desktop build injects `window.__TAURI__` at startup. We expose a single
 * boolean so any feature - auth, file manager, onboarding - can branch on
 * "running inside the native shell" without each one re-implementing the probe
 * or importing from another feature folder.
 *
 * Kept side-effect free and SSR/test safe: it never touches `window` unless it
 * exists, so importing this in a non-browser context (vitest, build tooling)
 * is harmless.
 */
export const isTauri =
  typeof window !== 'undefined' &&
  Boolean((window as { __TAURI__?: unknown }).__TAURI__);

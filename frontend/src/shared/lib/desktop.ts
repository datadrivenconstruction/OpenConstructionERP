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

/**
 * Sanitize a caller-supplied path so we only ever open a same-origin app route.
 *
 * Returns a clean path that starts with a single "/" and carries no scheme or
 * protocol-relative host, or `undefined` when the input is empty or unsafe (the
 * caller then opens the home page). Mirrors the guard the native command
 * applies, so both layers agree on what "the current page" may be.
 */
function safeAppPath(path?: string): string | undefined {
  if (!path) return undefined;
  if (!path.startsWith('/')) return undefined;
  if (path.startsWith('//')) return undefined;
  if (path.includes('://') || path.includes('\\')) return undefined;
  return path;
}

/**
 * Open the running app in the user's normal web browser (desktop only).
 *
 * In the Tauri shell the app is served at a local address like
 * http://127.0.0.1:8732/. This hands that address to the OS default browser so
 * people who prefer tabs over a separate window can use it there.
 *
 * Pass `path` (for example the current route) to open that exact page rather
 * than the home page. It first asks the native shell (the `open_app_in_browser`
 * command, which knows the dynamic port authoritatively). If that bridge is
 * missing for any reason it falls back to opening the same path on the current
 * origin, which inside the webview is already the local address. Returns true
 * when an open was attempted.
 */
export async function openAppInBrowser(path?: string): Promise<boolean> {
  if (!isTauri) return false;

  const cleanPath = safeAppPath(path);
  const tauri = (window as { __TAURI__?: Record<string, unknown> }).__TAURI__;
  const core = tauri?.core as
    | { invoke?: (cmd: string, args?: Record<string, unknown>) => Promise<unknown> }
    | undefined;
  const invoke =
    core?.invoke ??
    (tauri?.invoke as
      | ((cmd: string, args?: Record<string, unknown>) => Promise<unknown>)
      | undefined);

  if (invoke) {
    try {
      await invoke('open_app_in_browser', cleanPath ? { path: cleanPath } : {});
      return true;
    } catch {
      // Fall through to opening the current origin directly.
    }
  }

  try {
    window.open(window.location.origin + (cleanPath ?? '/'), '_blank', 'noopener');
    return true;
  } catch {
    return false;
  }
}

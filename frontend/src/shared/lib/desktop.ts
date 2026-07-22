// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
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

type TauriInvoke = (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;

/**
 * Resolve the Tauri `invoke` bridge exposed by `withGlobalTauri`.
 *
 * Returns the core invoke function (or the legacy top-level one) when running
 * inside the desktop shell, otherwise undefined. Both `openAppInBrowser` and
 * `openExternalUrl` reach native Rust commands through this rather than the
 * `@tauri-apps/*` npm packages, which are deliberately NOT part of the web
 * bundle - importing them at runtime in the built webview just throws.
 */
function getTauriInvoke(): TauriInvoke | undefined {
  const tauri = (window as { __TAURI__?: Record<string, unknown> }).__TAURI__;
  const core = tauri?.core as { invoke?: TauriInvoke } | undefined;
  return core?.invoke ?? (tauri?.invoke as TauriInvoke | undefined);
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
  const invoke = getTauriInvoke();

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

/**
 * Open an arbitrary external URL in the user's default browser (desktop only).
 *
 * In a web build a plain `<a target="_blank">` already opens a new tab, so
 * callers should reach for this only inside the Tauri shell, where the webview
 * swallows a target link and nothing opens. It calls the native
 * `open_external_url` command (which shells out to the OS opener) through the
 * `withGlobalTauri` invoke bridge. We deliberately do NOT import
 * `@tauri-apps/plugin-shell`: that package is not part of the bundle, so a
 * runtime import of it in the built webview just throws and every outbound link
 * silently dies. Returns true when an open was attempted, false otherwise.
 */
export async function openExternalUrl(url: string): Promise<boolean> {
  if (!isTauri || !url) return false;
  const invoke = getTauriInvoke();
  if (!invoke) return false;
  try {
    await invoke('open_external_url', { url });
    return true;
  } catch (err) {
    console.warn('open_external_url failed:', err);
    return false;
  }
}

/**
 * Open a URL in a genuinely new browser tab, never a chrome-less popup.
 *
 * Clicks a hidden anchor carrying rel="noopener" rather than passing a features
 * string to `window.open`: any non-empty features string (even just "noopener")
 * makes Chromium spawn a popup window with no address bar or back button
 * instead of a real tab. Use this for things the user opens to look at - a
 * generated PDF, a report - where a fresh surface is always wanted.
 */
export function openInNewTab(url: string): void {
  const a = document.createElement('a');
  a.href = url;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/**
 * Open a link the way the current build can actually honour.
 *
 * Web build: a real browser tab (see `openInNewTab`), so a link never lands in
 * a chrome-less popup window.
 *
 * Desktop (Tauri) shell: a webview cannot open a browser tab. A genuinely
 * external site (or a mail / tel link) is handed to the OS default browser, so
 * it opens with full navigation rather than a bare webview window; a same-origin
 * app route is followed in place, keeping the app shell and the signed-in
 * session instead of a stray window. Anything else (blob:, data:) falls back to
 * a new tab.
 */
export function openLink(url: string): void {
  let resolved: URL | null = null;
  try {
    resolved = new URL(url, window.location.href);
  } catch {
    resolved = null;
  }
  const scheme = resolved?.protocol.toLowerCase() ?? '';
  const isHttp = scheme === 'http:' || scheme === 'https:';
  const isExternalWeb = isHttp && resolved!.origin !== window.location.origin;
  const isMail = scheme === 'mailto:' || scheme === 'tel:';
  const isSameOriginRoute = isHttp && resolved!.origin === window.location.origin;

  if (isTauri) {
    if (isExternalWeb || isMail) {
      void openExternalUrl(resolved!.href);
      return;
    }
    if (isSameOriginRoute) {
      window.location.assign(resolved!.href);
      return;
    }
  }
  openInNewTab(url);
}

/**
 * Route every external-link click to the OS browser (desktop only).
 *
 * Inside the Tauri webview a plain `<a href="https://…" target="_blank">` goes
 * nowhere: the webview refuses to navigate off the local app origin and no new
 * window opens, so every outbound link in the UI (docs, GitHub, the marketing
 * site, contact mail) looks dead. This installs one capture-phase click
 * listener that catches those clicks before the webview swallows them and hands
 * the URL to the native opener. Same-origin app routes (react-router links,
 * in-app anchors) are left untouched so navigation still works normally.
 * Idempotent, and a no-op in a normal web build where anchors behave already.
 */
export function installDesktopExternalLinks(): void {
  if (!isTauri || typeof document === 'undefined') return;
  const flagged = window as { __oeExternalLinks?: boolean };
  if (flagged.__oeExternalLinks) return;
  flagged.__oeExternalLinks = true;

  document.addEventListener(
    'click',
    (event) => {
      // Left-click only; middle-click fires 'auxclick', keyboard activation
      // reports button 0. Never fight a click a component already handled.
      if (event.defaultPrevented || event.button !== 0) return;
      const origin = event.target as Element | null;
      const anchor = origin?.closest?.('a');
      if (!anchor) return;
      const href = anchor.getAttribute('href');
      if (!href) return;

      let resolved: URL;
      try {
        resolved = new URL(href, window.location.href);
      } catch {
        return;
      }
      const scheme = resolved.protocol.toLowerCase();
      const isWeb =
        (scheme === 'http:' || scheme === 'https:') &&
        resolved.origin !== window.location.origin;
      const isMail = scheme === 'mailto:';
      if (!isWeb && !isMail) return;

      // Genuinely external: stop the webview navigating and open it in the real
      // browser instead.
      event.preventDefault();
      void openExternalUrl(resolved.href);
    },
    true,
  );
}

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
import i18next from 'i18next';

import { useToastStore } from '@/stores/useToastStore';

import { copyToClipboard } from './browser';

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
 * Outcome of an "open in your browser" attempt.
 *
 * Deliberately an object and not a boolean. This helper used to return `true`
 * from every branch a desktop user could reach, so the `if (!ok)` guard at both
 * call sites was dead code and a failed open told the user nothing. Swapping
 * one truthy shape for another would have preserved that trap, so failure now
 * has to be read from a named field to be missed.
 */
export interface OpenInBrowserResult {
  /** True when the shell accepted the request. NOT a promise that a browser window appeared. */
  ok: boolean;
  /** Why it failed, as reported by the native command, when `ok` is false. */
  reason?: string;
}

/**
 * Open the running app in the user's normal web browser (desktop only).
 *
 * In the Tauri shell the app is served at a local address like
 * http://127.0.0.1:8732/. This hands that address to the OS default browser so
 * people who prefer tabs over a separate window can use it there.
 *
 * Pass `path` (for example the current route) to open that exact page rather
 * than the home page. It asks the native shell (the `open_app_in_browser`
 * command, which knows the dynamic port authoritatively), and reports back
 * whatever the shell said, including its error text.
 *
 * There is deliberately NO `window.open` fallback. This returns early unless
 * it is running inside the Tauri shell, and inside that shell a webview
 * swallows target navigation - which is precisely why every outbound link goes
 * through a native command instead (see `openExternalUrl` below). A fallback
 * could therefore only ever run in the one environment where it cannot work:
 * it opened nothing, reported success, and that is what made a failed open
 * completely silent.
 */
export async function openAppInBrowser(path?: string): Promise<OpenInBrowserResult> {
  if (!isTauri) return { ok: false, reason: 'Not running in the desktop app.' };

  const cleanPath = safeAppPath(path);
  const invoke = getTauriInvoke();
  if (!invoke) return { ok: false, reason: 'The desktop bridge is unavailable.' };

  try {
    await invoke('open_app_in_browser', cleanPath ? { path: cleanPath } : {});
    return { ok: true };
  } catch (err) {
    // The native command returns a human-readable string (for example "The app
    // is still starting. Please try again in a moment."), so pass it straight
    // through rather than replacing a specific cause with a generic warning.
    console.warn('open_app_in_browser failed:', err);
    return { ok: false, reason: typeof err === 'string' ? err : undefined };
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
 *
 * A false is also put on screen, see `reportLinkNotOpened`. The command can be
 * refused before it runs at all: the application is served from a loopback
 * address, which Tauri treats as a remote origin, so the access control list
 * decides whether the page may call this, and a refusal arrives here as a
 * rejected promise. Returning false quietly was what made that refusal
 * indistinguishable from a dead link.
 */
export async function openExternalUrl(url: string): Promise<boolean> {
  if (!isTauri || !url) return false;
  const invoke = getTauriInvoke();
  if (!invoke) {
    reportLinkNotOpened(url);
    return false;
  }
  try {
    await invoke('open_external_url', { url });
    return true;
  } catch (err) {
    console.warn('open_external_url failed:', err);
    reportLinkNotOpened(url);
    return false;
  }
}

/**
 * Put a link that did not open in front of the user, with the address.
 *
 * Every failure this reports used to be silent, and silent here is the worst
 * possible outcome: the click is swallowed by the capture-phase handler in
 * `installDesktopExternalLinks`, the webview never navigates, and the person is
 * left looking at a link that behaves like a picture of a link. A console
 * warning is not a message to a user.
 *
 * This lives in `openExternalUrl` rather than in `openLink` on purpose. Both
 * outbound paths, the explicit `openLink` call and the global anchor handler,
 * end here, so reporting at this one point covers both and cannot drift apart.
 *
 * The toast carries the address itself rather than an explanation of why the
 * shell said no, because the address is the part the user can act on: the
 * action copies it, and pasting it into a browser is the whole of the recovery.
 * The technical reason stays on the console for whoever is reading one.
 */
function reportLinkNotOpened(url: string): void {
  useToastStore.getState().addToast(
    {
      type: 'warning',
      title: i18next.t('desktop.open_in_browser_failed', {
        defaultValue: 'Could not open your browser',
      }),
      message: url,
      action: {
        label: i18next.t('common.copy', { defaultValue: 'Copy' }),
        onClick: () => {
          void copyToClipboard(url);
        },
      },
    },
    // Longer than the 4s default: this one asks the user to do something, and
    // an address is slower to read than a confirmation.
    { duration: 12_000 },
  );
}

/**
 * Show a file from the workspace in the operating system's file manager.
 *
 * Desktop only, and it reaches the native `reveal_path_in_os` command through
 * the same `withGlobalTauri` invoke bridge as everything else here rather than
 * `@tauri-apps/plugin-shell`, which is not in the bundle: importing it at
 * runtime in the built webview throws, so a call made that way dies before it
 * reaches the shell at all.
 *
 * The command opens the FOLDER holding the file, not the file, and refuses any
 * path that does not resolve inside this installation's data folder. Both rules
 * live in Rust rather than here, because a rule the page states is not a rule
 * the page is held to, and because deciding whether a path names a file needs
 * the filesystem: the regular expression this used to use guessed from the
 * extension, and it gets a folder called `2026.09` wrong in one direction and a
 * file with no extension wrong in the other.
 *
 * A false is put on screen, for the same reason `reportLinkNotOpened` exists.
 * The access control list can refuse this before it runs, and a refusal that
 * only reaches the console is indistinguishable to the user from a dead button.
 * That is precisely what happened here: the refusal text travelled to us inside
 * a bug report because it never appeared anywhere the person could see it.
 */
export async function revealPathInOS(path: string): Promise<boolean> {
  if (!isTauri || !path) return false;
  const invoke = getTauriInvoke();
  if (!invoke) {
    reportRevealFailed(path);
    return false;
  }
  try {
    await invoke('reveal_path_in_os', { path });
    return true;
  } catch (err) {
    console.warn('reveal_path_in_os failed:', err);
    reportRevealFailed(path, typeof err === 'string' ? err : undefined);
    return false;
  }
}

/**
 * Put a reveal that did not happen in front of the user, with the path.
 *
 * The native command answers with a finished sentence, so it is shown as it
 * stands rather than replaced by a generic warning: the difference between
 * "That file is not on this computer" and "Only files inside this workspace can
 * be shown" is the difference between a user knowing what to do next and not.
 * The path is the fallback message and is always what the action copies,
 * because pasting it into a file manager is the whole of the recovery.
 */
function reportRevealFailed(path: string, reason?: string): void {
  useToastStore.getState().addToast(
    {
      type: 'warning',
      title: i18next.t('desktop.reveal_failed', {
        defaultValue: 'Could not open that folder',
      }),
      message: reason || path,
      action: {
        label: i18next.t('common.copy', { defaultValue: 'Copy' }),
        onClick: () => {
          void navigator.clipboard?.writeText(path);
        },
      },
    },
    { duration: 12_000 },
  );
}

/**
 * Which server the desktop launcher has this window pointed at.
 *
 * `source` arrives as a finished English phrase from the launcher rather than
 * as a code to translate here, because the launcher itself has no translation
 * layer and the same phrase has to appear on its startup failure screen, which
 * this app never gets to render. One English sentence in two places beats one
 * translated here and a different English one there.
 */
export interface DesktopServerChoice {
  /** `local` when the launcher runs the server itself, `remote` when it does not. */
  mode: 'local' | 'remote';
  /** The address in use, canonicalised by the launcher. */
  url: string;
  /** Which layer of the launcher's precedence chain decided this. */
  source: string;
  /** True when this user's own saved choice is what decided it. */
  fromUserSetting: boolean;
}

/**
 * Ask the launcher which server this window is talking to.
 *
 * Returns undefined when there is no answer to be had, and deliberately does
 * not distinguish "not running in the desktop shell" from "the access control
 * list refused the call", because the caller does the same thing in both cases:
 * fall back to what the page can see without asking anyone, which is its own
 * origin.
 *
 * That refusal is a designed state, not a bug. In remote mode the application
 * is served by a server whose address a person typed, and that origin is
 * granted no native commands at all, so this call is refused there by design.
 * Probing the outcome is therefore the honest way to find out whether this page
 * may configure the launcher: it measures the actual grant instead of guessing
 * it from the hostname and drifting apart from the capability files.
 */
export async function getDesktopServerChoice(): Promise<DesktopServerChoice | undefined> {
  if (!isTauri) return undefined;
  const invoke = getTauriInvoke();
  if (!invoke) return undefined;
  try {
    const answer = await invoke('get_server_choice');
    if (!answer || typeof answer !== 'object') return undefined;
    return answer as DesktopServerChoice;
  } catch (err) {
    console.warn('get_server_choice failed:', err);
    return undefined;
  }
}

/**
 * Outcome of asking the launcher to change which server it uses.
 *
 * An object rather than a boolean for the same reason `OpenInBrowserResult` is
 * one: the launcher validates the address and its refusal carries the sentence
 * explaining why, and that sentence is the entire value of the round trip. A
 * boolean would throw away the only part the user can act on.
 */
export interface SetServerResult {
  ok: boolean;
  /** The launcher's own explanation when `ok` is false. */
  reason?: string;
}

/**
 * Save which server the desktop launcher should use from the next start.
 *
 * Pass null to clear this user's choice, which hands the decision back to the
 * environment variable and the file an administrator deploys. That is the only
 * way back to being centrally managed once somebody has chosen for themselves,
 * so it is a real argument and not an oversight.
 *
 * Takes effect on the next start, never on this one. Repointing a running
 * window at a different database mid-session would leave every open form, every
 * cached query and every unsaved edit belonging to the previous server, so the
 * launcher only ever reads this while starting.
 */
export async function setDesktopServerChoice(
  choice: { mode: 'local' } | { mode: 'remote'; url: string } | null,
): Promise<SetServerResult> {
  if (!isTauri) return { ok: false, reason: 'Not running in the desktop app.' };
  const invoke = getTauriInvoke();
  if (!invoke) return { ok: false, reason: 'The desktop bridge is unavailable.' };
  try {
    await invoke('set_server_choice', {
      mode: choice?.mode ?? null,
      url: choice && choice.mode === 'remote' ? choice.url : null,
    });
    return { ok: true };
  } catch (err) {
    return { ok: false, reason: typeof err === 'string' ? err : undefined };
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

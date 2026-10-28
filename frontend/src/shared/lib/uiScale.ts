// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Interface size, shown in Settings as "Text size".
 *
 * How the app is sized decides how it can be scaled, and each alternative was
 * measured before this one was picked:
 *
 * - The root font-size does not move the text. The Tailwind type scale is
 *   declared in px (`text-xs` is 11px, `text-sm` 13px, `text-base` 15px), the
 *   source carries about 2,200 arbitrary `text-[Npx]` classes and ~200 inline
 *   numeric font sizes, and AG Grid reads `--ag-font-size: 13px`. The 15px on
 *   `html` only drives rem spacing, so scaling it grows the gaps and leaves the
 *   letters where they are.
 * - CSS `zoom` on `<html>` scales everything but splits the coordinate space.
 *   Measured in Chromium 153 at 125%: a fixed popover placed from its anchor's
 *   getBoundingClientRect lands 62.5px right and 40.6px low of an anchor at
 *   (200, 100), `window.innerWidth` stays at the unzoomed width so Tailwind
 *   breakpoints do not react, a canvas reports clientWidth 200 against a rect
 *   of 250, and `devicePixelRatio` stays at 1 so PDF.js and Three.js render a
 *   1x backing store that is then blown up. About 40 files read
 *   getBoundingClientRect and 29 render through portals, so this is not a
 *   corner case.
 * - Native webview zoom is what browser zoom is: the CSS viewport shrinks and
 *   `devicePixelRatio` grows, so rects, pointer coordinates, breakpoints and
 *   canvases all stay in one space. Same probe: popover error 0, innerWidth
 *   1024 on a 1280px window, devicePixelRatio 1.25.
 *
 * So the desktop app zooms its own webview through Tauri, and the web app
 * leaves it to the browser's zoom, which already is that mechanism and which
 * the browser remembers per site. A page cannot set browser zoom, and faking it
 * with CSS would ship the drift measured above.
 *
 * The chosen size is kept per device in localStorage. In the desktop app that
 * storage belongs to the loopback origin the launcher serves from, the same
 * place the theme and language live.
 */
import { isTauri, setDesktopWebviewZoom } from './desktop';

/** The sizes offered in Settings, as zoom factors. 1 is the default. */
export const UI_SCALE_STEPS: readonly number[] = [0.9, 1, 1.1, 1.25, 1.5];

export const DEFAULT_UI_SCALE = 1;

export const UI_SCALE_STORAGE_KEY = 'oe_ui_scale';

/** True where the app can change its own size: the desktop shell only. */
export const canSetUiScale = isTauri;

/**
 * Snap any value to the nearest offered step.
 *
 * Anything that is not a positive finite number falls back to the default, and
 * a number outside the range lands on the nearest end, so a hand-edited or
 * stale stored value can never zoom the window to something unusable.
 */
export function normalizeUiScale(value: unknown): number {
  const parsed =
    typeof value === 'number' ? value : typeof value === 'string' ? Number.parseFloat(value) : Number.NaN;
  if (!Number.isFinite(parsed) || parsed <= 0) return DEFAULT_UI_SCALE;
  let best = DEFAULT_UI_SCALE;
  for (const step of UI_SCALE_STEPS) {
    if (Math.abs(step - parsed) < Math.abs(best - parsed)) best = step;
  }
  return best;
}

/**
 * The saved size, or the default when nothing usable is stored.
 *
 * Storage can be missing or throw on access (private windows, blocked site
 * data), and neither may stop the app from starting.
 */
export function readUiScale(): number {
  try {
    return normalizeUiScale(window.localStorage.getItem(UI_SCALE_STORAGE_KEY));
  } catch {
    return DEFAULT_UI_SCALE;
  }
}

/**
 * Save a size for the next start. The default is stored as no entry at all.
 *
 * A failed write is swallowed on purpose: the size still applies to this
 * session, it just will not be remembered.
 */
export function writeUiScale(scale: number): void {
  const value = normalizeUiScale(scale);
  try {
    if (value === DEFAULT_UI_SCALE) window.localStorage.removeItem(UI_SCALE_STORAGE_KEY);
    else window.localStorage.setItem(UI_SCALE_STORAGE_KEY, String(value));
  } catch {
    // Storage unavailable: nothing to remember it in.
  }
}

/** Apply a size to the window now. Resolves false where it cannot be applied. */
export function applyUiScale(scale: number): Promise<boolean> {
  if (!canSetUiScale) return Promise.resolve(false);
  return setDesktopWebviewZoom(normalizeUiScale(scale));
}

/**
 * Re-apply the saved size at startup.
 *
 * Returns null when there is nothing to wait for (the web build, or the default
 * size, which a freshly started webview already has), otherwise the pending
 * call, so the first render can wait for it and never paint at the wrong size.
 */
export function applyStoredUiScale(): Promise<boolean> | null {
  if (!canSetUiScale) return null;
  const scale = readUiScale();
  if (scale === DEFAULT_UI_SCALE) return null;
  return applyUiScale(scale);
}

/** True on Apple platforms, where the zoom shortcuts use Cmd instead of Ctrl. */
export function isApplePlatform(): boolean {
  if (typeof navigator === 'undefined') return false;
  return /Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent || '');
}

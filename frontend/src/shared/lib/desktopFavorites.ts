/**
 * Desktop-local favorites (bookmarks) for the browser-style toolbar.
 *
 * The desktop shell shows a slim browser chrome above the app. Its star button
 * bookmarks the page the user is on, the same way a browser does. The app has
 * surface-specific "saved views" (files, BIM viewer), but no global "favorite
 * pages" concept, so this is a lightweight, self-contained list that lives on
 * the desktop only.
 *
 * Persistence is the webview's localStorage, which is per-origin and survives
 * app restarts. We intentionally avoid a heavier Tauri store plugin: a small
 * JSON array in localStorage is enough, adds no dependency, and keeps the data
 * readable. The list is capped so it never grows unbounded.
 *
 * Kept framework-free and side-effect light so it is easy to unit test and so
 * importing it in a non-browser context (vitest, build tooling) is harmless.
 */

export interface DesktopFavorite {
  /** App route path, always starting with "/" (for example "/boq"). */
  path: string;
  /** Human label shown in the list (falls back to the path). */
  label: string;
  /** Epoch millis the favorite was added, for stable ordering. */
  addedAt: number;
}

const STORAGE_KEY = 'oe_desktop_favorites';
const MAX_FAVORITES = 50;

/** Read the favorites list from storage (newest first). Never throws. */
export function readFavorites(): DesktopFavorite[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    const clean = parsed
      .filter(
        (f): f is DesktopFavorite =>
          !!f &&
          typeof f === 'object' &&
          typeof (f as DesktopFavorite).path === 'string' &&
          (f as DesktopFavorite).path.startsWith('/'),
      )
      .map((f) => ({
        path: f.path,
        label: typeof f.label === 'string' && f.label.trim() ? f.label : f.path,
        addedAt: typeof f.addedAt === 'number' ? f.addedAt : 0,
      }));
    // Newest first so the most recent bookmark is easy to reach.
    return clean.sort((a, b) => b.addedAt - a.addedAt).slice(0, MAX_FAVORITES);
  } catch {
    return [];
  }
}

function writeFavorites(list: DesktopFavorite[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(list.slice(0, MAX_FAVORITES)));
  } catch {
    // Private mode or storage blocked; favorites are best-effort.
  }
}

/** True when the given path is already bookmarked. */
export function isFavorite(path: string, list?: DesktopFavorite[]): boolean {
  const favs = list ?? readFavorites();
  return favs.some((f) => f.path === path);
}

/**
 * Add a favorite (no-op if the path is already there). Returns the new list so
 * callers can update state without a second read.
 */
export function addFavorite(path: string, label: string): DesktopFavorite[] {
  if (!path.startsWith('/')) return readFavorites();
  const list = readFavorites();
  if (list.some((f) => f.path === path)) return list;
  const next = [{ path, label: label.trim() || path, addedAt: Date.now() }, ...list];
  writeFavorites(next);
  return next;
}

/** Remove a favorite by path. Returns the new list. */
export function removeFavorite(path: string): DesktopFavorite[] {
  const next = readFavorites().filter((f) => f.path !== path);
  writeFavorites(next);
  return next;
}

/** Toggle a favorite for the given path. Returns the new list. */
export function toggleFavorite(path: string, label: string): DesktopFavorite[] {
  return isFavorite(path) ? removeFavorite(path) : addFavorite(path, label);
}

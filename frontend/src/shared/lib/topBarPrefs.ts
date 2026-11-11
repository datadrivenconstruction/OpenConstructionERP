/**
 * Which optional items of the top bar this person hides, kept on this device
 * like the other interface preferences (`footerPrefs.ts`). Everything is shown
 * by default. Notifications, Help and the account menu are not configurable:
 * they are the way back to every other control.
 */
import { useSyncExternalStore } from 'react';

export const TOP_BAR_ITEMS = [
  'pack',
  'journey',
  'search',
  'askAi',
  'news',
  'moduleBuilder',
  'supportUs',
  'subscribe',
  'bugReport',
  'language',
  'theme',
] as const;
export type TopBarItem = (typeof TOP_BAR_ITEMS)[number];

/** `true` means the item is hidden. */
export type TopBarPrefs = Record<TopBarItem, boolean>;

export const DEFAULT_TOP_BAR_PREFS: TopBarPrefs = Object.fromEntries(
  TOP_BAR_ITEMS.map((k) => [k, false]),
) as TopBarPrefs;
export const TOP_BAR_PREFS_KEY = 'oe_topbar_prefs_v1';

const listeners = new Set<() => void>();
let cached: TopBarPrefs | null = null;

function sanitize(raw: unknown): TopBarPrefs {
  const src = (raw && typeof raw === 'object' ? raw : {}) as Partial<Record<TopBarItem, unknown>>;
  const out = { ...DEFAULT_TOP_BAR_PREFS };
  for (const k of TOP_BAR_ITEMS) out[k] = src[k] === true;
  return out;
}

export function readTopBarPrefs(): TopBarPrefs {
  if (cached) return cached;
  try {
    cached = sanitize(JSON.parse(localStorage.getItem(TOP_BAR_PREFS_KEY) ?? 'null'));
  } catch {
    cached = { ...DEFAULT_TOP_BAR_PREFS };
  }
  return cached;
}

export function writeTopBarPrefs(next: TopBarPrefs): void {
  cached = sanitize(next);
  try {
    localStorage.setItem(TOP_BAR_PREFS_KEY, JSON.stringify(cached));
  } catch {
    /* storage unavailable: applies until reload */
  }
  listeners.forEach((cb) => cb());
}

/** Drop the in-memory copy so the next read goes to storage (other tab, tests). */
export function resetTopBarPrefsCache(): void {
  cached = null;
  listeners.forEach((cb) => cb());
}

export function subscribeTopBarPrefs(cb: () => void): () => void {
  listeners.add(cb);
  const onStorage = (e: StorageEvent) => {
    if (e.key === TOP_BAR_PREFS_KEY || e.key === null) resetTopBarPrefsCache();
  };
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(cb);
    window.removeEventListener('storage', onStorage);
  };
}

/** Live top bar preferences; the header and the settings card both read this. */
export function useTopBarPrefs(): TopBarPrefs {
  return useSyncExternalStore(subscribeTopBarPrefs, readTopBarPrefs, () => DEFAULT_TOP_BAR_PREFS);
}

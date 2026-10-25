// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Which optional buttons of the sidebar footer this person hides, kept on this
 * device like the other interface preferences (`workPrefs.ts`).
 *
 * Only the tiles that are not menu routes live here. Settings, Users and About
 * are menu routes and share the per-user hidden list that the "Edit menu"
 * editor writes (`useHiddenModules`), so there is one answer per tile.
 *
 * Settings stays reachable whatever is stored: the profile menu in the header
 * always offers it, and so do the command palette and the `G ,` shortcut.
 */
import { useSyncExternalStore } from 'react';

export const FOOTER_ITEMS = ['editMenu', 'github', 'community'] as const;
export type FooterItem = (typeof FOOTER_ITEMS)[number];

/** `true` means the button is hidden. Everything is shown by default. */
export type FooterPrefs = Record<FooterItem, boolean>;

export const DEFAULT_FOOTER_PREFS: FooterPrefs = { editMenu: false, github: false, community: false };
export const FOOTER_PREFS_KEY = 'oe_sidebar_footer_v1';

/** The footer tiles that are menu routes, hidden through the per-user hidden list. */
export const FOOTER_ROUTE_ITEMS = ['/settings', '/users', '/about'] as const;

const listeners = new Set<() => void>();
let cached: FooterPrefs | null = null;

function sanitize(raw: unknown): FooterPrefs {
  const src = (raw && typeof raw === 'object' ? raw : {}) as Partial<Record<FooterItem, unknown>>;
  return {
    editMenu: src.editMenu === true,
    github: src.github === true,
    community: src.community === true,
  };
}

export function readFooterPrefs(): FooterPrefs {
  if (cached) return cached;
  try {
    cached = sanitize(JSON.parse(localStorage.getItem(FOOTER_PREFS_KEY) ?? 'null'));
  } catch {
    cached = { ...DEFAULT_FOOTER_PREFS };
  }
  return cached;
}

export function writeFooterPrefs(next: FooterPrefs): void {
  cached = sanitize(next);
  try {
    localStorage.setItem(FOOTER_PREFS_KEY, JSON.stringify(cached));
  } catch {
    /* storage unavailable: applies until reload */
  }
  listeners.forEach((cb) => cb());
}

/** Drop the in-memory copy so the next read goes to storage (other tab, tests). */
export function resetFooterPrefsCache(): void {
  cached = null;
  listeners.forEach((cb) => cb());
}

export function subscribeFooterPrefs(cb: () => void): () => void {
  listeners.add(cb);
  const onStorage = (e: StorageEvent) => {
    if (e.key === FOOTER_PREFS_KEY || e.key === null) resetFooterPrefsCache();
  };
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(cb);
    window.removeEventListener('storage', onStorage);
  };
}

/** Live footer preferences; the sidebar and the settings card both read this. */
export function useFooterPrefs(): FooterPrefs {
  return useSyncExternalStore(subscribeFooterPrefs, readFooterPrefs, () => DEFAULT_FOOTER_PREFS);
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Local menu usage counts and the suggestion rules built on them. Nothing
 * leaves the browser and nothing changes the menu by itself: a suggestion is
 * only applied when the user presses Accept.
 */

export const DAY_MS = 24 * 60 * 60 * 1000;
export const STALE_DAYS = 30;
export const FREQUENT_COUNT = 10;
const DISMISS_DAYS = 30;
const USAGE_KEY = 'oe.menu_usage.v1';

export interface MenuUsage {
  /** When tracking started; no item is called unused before 30 days of data. */
  since: number;
  items: Record<string, { count: number; last: number }>;
  /** Suggestion key -> time until which it stays quiet. */
  dismissed: Record<string, number>;
}

export interface MenuSuggestion {
  key: string;
  kind: 'hide' | 'promote';
  route: string;
  /** Days since last opened (hide) or number of opens (promote), for the reason line. */
  value: number;
  /** 0-1, grows with the evidence. */
  confidence: number;
}

export function emptyUsage(now: number): MenuUsage {
  return { since: now, items: {}, dismissed: {} };
}

export function recordVisit(usage: MenuUsage, route: string, now: number): MenuUsage {
  const prev = usage.items[route];
  return {
    ...usage,
    items: { ...usage.items, [route]: { count: (prev?.count ?? 0) + 1, last: now } },
  };
}

export function dismissSuggestion(usage: MenuUsage, key: string, now: number): MenuUsage {
  return { ...usage, dismissed: { ...usage.dismissed, [key]: now + DISMISS_DAYS * DAY_MS } };
}

export interface SuggestionInput {
  usage: MenuUsage;
  now: number;
  /** Rows currently on screen in the menu. */
  visibleRoutes: readonly string[];
  pinned: readonly string[];
  maxPinned: number;
  /** Rows that may never be suggested for hiding (home, projects). */
  keep: ReadonlySet<string>;
}

export function suggestMenuChanges(input: SuggestionInput): MenuSuggestion[] {
  const { usage, now, visibleRoutes, pinned, maxPinned, keep } = input;
  const quiet = (key: string) => (usage.dismissed[key] ?? 0) > now;
  const out: MenuSuggestion[] = [];

  if (pinned.length < maxPinned) {
    for (const [route, stat] of Object.entries(usage.items)) {
      if (stat.count < FREQUENT_COUNT || pinned.includes(route) || !visibleRoutes.includes(route)) continue;
      if (now - stat.last >= STALE_DAYS * DAY_MS) continue;
      const key = `promote:${route}`;
      if (quiet(key)) continue;
      out.push({ key, kind: 'promote', route, value: stat.count, confidence: Math.min(1, stat.count / 30) });
    }
  }

  const trackedDays = Math.floor((now - usage.since) / DAY_MS);
  if (trackedDays >= STALE_DAYS) {
    for (const route of visibleRoutes) {
      if (keep.has(route) || pinned.includes(route)) continue;
      const last = usage.items[route]?.last ?? usage.since;
      const days = Math.floor((now - last) / DAY_MS);
      if (days < STALE_DAYS) continue;
      const key = `hide:${route}`;
      if (quiet(key)) continue;
      out.push({ key, kind: 'hide', route, value: days, confidence: Math.min(1, days / 90) });
    }
  }

  // Promotions first (they add, never remove), then the stalest rows.
  return out.sort((a, b) => (a.kind === b.kind ? b.confidence - a.confidence : a.kind === 'promote' ? -1 : 1));
}

export function readUsage(now: number): MenuUsage {
  try {
    const raw = localStorage.getItem(USAGE_KEY);
    if (raw) {
      const p = JSON.parse(raw) as Partial<MenuUsage>;
      if (typeof p.since === 'number' && p.items && typeof p.items === 'object') {
        return { since: p.since, items: p.items, dismissed: p.dismissed ?? {} };
      }
    }
  } catch {
    /* storage unavailable */
  }
  return emptyUsage(now);
}

export function writeUsage(usage: MenuUsage): void {
  try {
    localStorage.setItem(USAGE_KEY, JSON.stringify(usage));
  } catch {
    /* storage unavailable */
  }
}

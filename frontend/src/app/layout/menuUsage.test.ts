import { describe, expect, it } from 'vitest';
import { DAY_MS, dismissSuggestion, emptyUsage, recordVisit, suggestMenuChanges, type MenuUsage } from './menuUsage';

const T0 = Date.UTC(2026, 0, 1);
const keep = new Set(['/']);
const base = { pinned: [] as string[], maxPinned: 5, keep };

function visits(u: MenuUsage, route: string, n: number, at: number) {
  for (let i = 0; i < n; i += 1) u = recordVisit(u, route, at);
  return u;
}

describe('menu suggestions', () => {
  it('says nothing about unused rows before 30 days of data', () => {
    const now = T0 + 10 * DAY_MS;
    expect(suggestMenuChanges({ ...base, usage: emptyUsage(T0), now, visibleRoutes: ['/rfi'] })).toEqual([]);
  });

  it('suggests hiding a row not opened in 30+ days, with the day count', () => {
    let u = emptyUsage(T0);
    u = recordVisit(u, '/rfi', T0 + DAY_MS);
    u = recordVisit(u, '/boq', T0 + 40 * DAY_MS);
    const now = T0 + 35 * DAY_MS;
    const out = suggestMenuChanges({ ...base, usage: u, now, visibleRoutes: ['/', '/rfi', '/boq'] });
    expect(out).toEqual([expect.objectContaining({ kind: 'hide', route: '/rfi', value: 34 })]);
  });

  it('never suggests hiding a kept or pinned row', () => {
    const now = T0 + 60 * DAY_MS;
    const out = suggestMenuChanges({ ...base, pinned: ['/rfi'], usage: emptyUsage(T0), now, visibleRoutes: ['/', '/rfi'] });
    expect(out).toEqual([]);
  });

  it('promotes a frequent row first, unless pins are full', () => {
    const u = visits(emptyUsage(T0), '/boq', 12, T0 + DAY_MS);
    const now = T0 + 2 * DAY_MS;
    const out = suggestMenuChanges({ ...base, usage: u, now, visibleRoutes: ['/boq'] });
    expect(out[0]).toMatchObject({ kind: 'promote', route: '/boq', value: 12 });
    expect(suggestMenuChanges({ ...base, maxPinned: 0, usage: u, now, visibleRoutes: ['/boq'] })).toEqual([]);
  });

  it('Not now keeps a suggestion quiet for 30 days', () => {
    let u = visits(emptyUsage(T0), '/boq', 12, T0);
    u = dismissSuggestion(u, 'promote:/boq', T0);
    const input = { ...base, usage: u, visibleRoutes: ['/boq'] };
    expect(suggestMenuChanges({ ...input, now: T0 + 5 * DAY_MS })).toEqual([]);
    const later = recordVisit(u, '/boq', T0 + 29 * DAY_MS);
    expect(suggestMenuChanges({ ...input, usage: later, now: T0 + 31 * DAY_MS })).toEqual([
      expect.objectContaining({ kind: 'promote', route: '/boq' }),
    ]);
  });
});

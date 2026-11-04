import { beforeEach, describe, expect, it } from 'vitest';
import { REF_TTL_MS, clearProjectRefs, getRef, putRef, resetRefCacheForTests, serverNowMs } from './refCache';

const DAY = 86_400_000;
const T0 = Date.parse('2026-11-01T08:00:00Z');

describe('refCache', () => {
  beforeEach(() => resetRefCacheForTests());

  it('returns nothing before anything is stored', async () => {
    expect(await getRef('p1', 'punch_items')).toBeNull();
  });

  it('round-trips a list per project and kind', async () => {
    await putRef('p1', 'punch_items', [{ id: 'a' }], new Date(T0).toISOString(), T0);
    await putRef('p2', 'punch_items', [{ id: 'b' }], new Date(T0).toISOString(), T0);
    const r = await getRef<{ id: string }[]>('p1', 'punch_items', T0 + 1000);
    expect(r?.payload).toEqual([{ id: 'a' }]);
    expect(r?.stale).toBe(false);
    expect(await getRef('p1', 'inspections', T0)).toBeNull();
  });

  it('goes stale after the TTL but is still returned', async () => {
    await putRef('p1', 'inspections', [1], new Date(T0).toISOString(), T0);
    const fresh = await getRef('p1', 'inspections', T0 + REF_TTL_MS - 1);
    const old = await getRef('p1', 'inspections', T0 + REF_TTL_MS + DAY);
    expect(fresh?.stale).toBe(false);
    expect(old?.stale).toBe(true);
    expect(old?.payload).toEqual([1]);
  });

  it('judges age by the server clock, not a phone that runs a week ahead', async () => {
    const phoneNow = T0 + 7 * DAY; // phone clock wrong by a week
    await putRef('p1', 'roster', ['x'], new Date(T0).toISOString(), phoneNow);
    const r = await getRef('p1', 'roster', phoneNow + 2 * DAY);
    expect(Math.round((r?.ageMs ?? 0) / DAY)).toBe(2);
    expect(r?.stale).toBe(false);
  });

  it('falls back to the device clock when the server time is unreadable', () => {
    expect(serverNowMs('garbage', 42)).toBe(42);
    expect(serverNowMs(null, 7)).toBe(7);
  });

  it('clears one project only', async () => {
    await putRef('p1', 'roster', [1], null, T0);
    await putRef('p2', 'roster', [2], null, T0);
    await clearProjectRefs('p1');
    expect(await getRef('p1', 'roster', T0)).toBeNull();
    expect(await getRef('p2', 'roster', T0)).not.toBeNull();
  });
});

describe('clearAllRefs', () => {
  it('forgets every project', async () => {
    const { clearAllRefs } = await import('./refCache');
    await putRef('p1', 'punch_items', [1], null, T0);
    await putRef('p2', 'roster', [2], null, T0);
    await clearAllRefs();
    expect(await getRef('p1', 'punch_items', T0)).toBeNull();
    expect(await getRef('p2', 'roster', T0)).toBeNull();
  });
});

import { describe, it, expect } from 'vitest';
import { PI_QUERY_STALE_MS as HERO_STALE_MS } from '../components/ProjectKPIHero';
import { PI_QUERY_STALE_MS as GRID_STALE_MS } from '../components/ProjectAnalyticsGrid';

/**
 * RFC 25 dropped the Project Intelligence client-side cache TTL from 5 min
 * to 60 s so the Estimation Dashboard reflects sibling-module edits within
 * one minute of a save. Both new widgets consume the same constant so the
 * dashboard refreshes in lockstep.
 */

describe('Project Intelligence cache TTL (RFC 25)', () => {
  it('ProjectKPIHero uses a 60 s staleTime', () => {
    expect(HERO_STALE_MS).toBe(60_000);
  });

  it('ProjectAnalyticsGrid uses the same 60 s staleTime', () => {
    expect(GRID_STALE_MS).toBe(60_000);
  });

  it('both widgets agree on the cache TTL', () => {
    expect(HERO_STALE_MS).toBe(GRID_STALE_MS);
  });
});

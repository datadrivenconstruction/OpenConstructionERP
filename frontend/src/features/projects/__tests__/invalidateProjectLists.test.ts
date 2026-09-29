import { describe, expect, it } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { invalidateProjectLists } from '../invalidateProjectLists';

describe('invalidateProjectLists', () => {
  it('marks every list a deleted or restored project appears in as stale', () => {
    const client = new QueryClient();
    const keys = [
      ['projects'],
      ['portfolio-analytics'],
      ['dashboard-project-cards'],
      ['analytics', 'overview'],
      ['portfolio', 'tree'],
    ];
    for (const key of keys) client.setQueryData(key, []);
    // A query outside the project lists, so the test fails if everything is
    // invalidated rather than the lists alone.
    client.setQueryData(['boq', 'positions'], []);

    invalidateProjectLists(client);

    for (const key of keys) {
      expect(client.getQueryState(key)?.isInvalidated, JSON.stringify(key)).toBe(true);
    }
    expect(client.getQueryState(['boq', 'positions'])?.isInvalidated).toBe(false);
  });
});

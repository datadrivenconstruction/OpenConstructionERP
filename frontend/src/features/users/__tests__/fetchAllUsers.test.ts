import { describe, it, expect, vi, beforeEach } from 'vitest';

const apiGet = vi.fn();
vi.mock('@/shared/lib/api', () => ({ apiGet: (...a: unknown[]) => apiGet(...a) }));

import { fetchAllUsers } from '../api';

const page = (n: number) => Array.from({ length: n }, (_, i) => ({ id: String(i) }));

describe('fetchAllUsers', () => {
  beforeEach(() => apiGet.mockReset());

  it('keeps paging while a full page comes back', async () => {
    apiGet.mockResolvedValueOnce(page(500)).mockResolvedValueOnce(page(120));
    const all = await fetchAllUsers();
    expect(all).toHaveLength(620);
    expect(apiGet.mock.calls[1]![0]).toContain('offset=500');
  });
});

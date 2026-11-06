import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiGet = vi.fn();
vi.mock('@/shared/lib/api', () => ({ apiGet, apiPost: vi.fn(), apiPatch: vi.fn(), apiDelete: vi.fn() }));

const { fetchProjectOffers, fetchTextBlocks } = await import('./api');

describe('offers list envelopes', () => {
  beforeEach(() => apiGet.mockReset());

  it('reads the offers page envelope and asks for the whole project list', async () => {
    apiGet.mockResolvedValue({ items: [{ id: 'o1' }], total: 1, offset: 0, limit: 500 });
    await expect(fetchProjectOffers('p1')).resolves.toEqual([{ id: 'o1' }]);
    expect(apiGet).toHaveBeenCalledWith('/v1/offers/?project_id=p1&limit=500');
  });

  it('reads the text library page envelope', async () => {
    apiGet.mockResolvedValue({ items: [{ id: 't1' }], total: 1, offset: 0, limit: 1000 });
    await expect(fetchTextBlocks('p1', 'DE')).resolves.toEqual([{ id: 't1' }]);
    expect(apiGet).toHaveBeenCalledWith('/v1/offers/texts?project_id=p1&country=DE&limit=1000');
  });
});

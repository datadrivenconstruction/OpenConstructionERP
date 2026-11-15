// Edge cases of the MoC REST helpers: filters, every FSM action, error propagation.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const apiMocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));
vi.mock('@/shared/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/shared/lib/api')>()),
  ...apiMocks,
}));

import { fetchMoCEntries, transitionMoCEntry, addMoCImpact, type MoCTransition } from '../api';

describe('moc api edges', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.apiGet.mockResolvedValue([]);
    apiMocks.apiPost.mockResolvedValue({});
  });

  it('an empty status filter is not sent', async () => {
    await fetchMoCEntries('p1', '');
    expect(apiMocks.apiGet).toHaveBeenCalledWith('/v1/moc/?project_id=p1');
  });

  it('encodes the project id in the query', async () => {
    await fetchMoCEntries('a&b', 'proposed');
    const url = apiMocks.apiGet.mock.calls[0]![0] as string;
    expect(Object.fromEntries(new URLSearchParams(url.split('?')[1]))).toEqual({
      project_id: 'a&b',
      status: 'proposed',
    });
  });

  it.each(['review', 'accept', 'decline', 'implement'] as MoCTransition[])('%s posts to its own action route', async (action) => {
    await transitionMoCEntry('m1', action, 'because');
    expect(apiMocks.apiPost).toHaveBeenCalledWith(`/v1/moc/m1/${action}`, { notes: 'because' });
  });

  it('propagates a rejected transition (e.g. illegal FSM step)', async () => {
    apiMocks.apiPost.mockRejectedValue(new Error('409 invalid transition'));
    await expect(transitionMoCEntry('m1', 'implement')).rejects.toThrow('409 invalid transition');
  });

  it('propagates list failures', async () => {
    apiMocks.apiGet.mockRejectedValue(new Error('offline'));
    await expect(fetchMoCEntries('p1')).rejects.toThrow('offline');
  });

  it('sends impact payloads through unchanged', async () => {
    const payload = { impact_area: 'schedule', severity: 'high', schedule_delta_days: -3 };
    await addMoCImpact('m1', payload);
    expect(apiMocks.apiPost).toHaveBeenCalledWith('/v1/moc/m1/impacts', payload);
  });
});

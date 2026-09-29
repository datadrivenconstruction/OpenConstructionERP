// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { fetchWithAuth } from './api';
import { useAuthStore } from '@/stores/useAuthStore';

const reply = (status: number, body: unknown = {}) =>
  ({ ok: status >= 200 && status < 300, status, statusText: '', json: async () => body }) as Response;

const authOf = (init: unknown) => new Headers((init as RequestInit | undefined)?.headers).get('Authorization');

describe('fetchWithAuth', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    useAuthStore.getState().setTokens('old_access', 'old_refresh', true, 'user@example.com');
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends the bearer token', async () => {
    const fetchMock = vi.fn().mockResolvedValue(reply(200));
    vi.stubGlobal('fetch', fetchMock);

    const res = await fetchWithAuth('/api/v1/stream', { method: 'POST', body: '{}' });

    expect(res.status).toBe(200);
    expect(authOf(fetchMock.mock.calls[0]![1])).toBe('Bearer old_access');
  });

  it('refreshes once on a 401 and replays the call with the new token', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reply(401))
      .mockResolvedValueOnce(reply(200, { access_token: 'new_access', refresh_token: 'new_refresh' }))
      .mockResolvedValueOnce(reply(200));
    vi.stubGlobal('fetch', fetchMock);

    const res = await fetchWithAuth('/api/v1/stream');

    expect(res.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1]![0]).toBe('/api/v1/users/auth/refresh/');
    expect(authOf(fetchMock.mock.calls[2]![1])).toBe('Bearer new_access');
  });

  it('hands the 401 back and keeps the session when the refresh server is down', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(reply(401)).mockResolvedValueOnce(reply(503));
    vi.stubGlobal('fetch', fetchMock);

    const res = await fetchWithAuth('/api/v1/stream');

    expect(res.status).toBe(401);
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
  });
});

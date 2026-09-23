// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The transport sorts requests offline by method alone: a GET is answered from
// the offline cache, anything else is queued for replay and reported to the
// user as "Saved offline", with `undefined` handed back as its answer. That is
// right for a change and wrong for a read that travels as a POST only because
// its question does not fit in a URL, such as the bill register asking for the
// bills of forty projects at once. Queued, that read would tell the estimator
// a list they merely opened was saved, give the screen nothing to draw, and be
// replayed on reconnect for nobody.
//
// `readOnly: true` makes such a POST behave as the GET it stands in for. What
// is pinned here is both halves of that, because the option lives in the
// transport every screen shares: the read is served from the cache and never
// queued, and a POST that did not opt in is queued exactly as before.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const store = vi.hoisted(() => ({
  cacheResponse: vi.fn(async (_key: string, _data: unknown) => {}),
  getCachedResponse: vi.fn(async (_key: string): Promise<unknown> => null),
  queueMutation: vi.fn(async (_mutation: unknown) => {}),
}));

vi.mock('../offlineStore', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../offlineStore')>()),
  cacheResponse: store.cacheResponse,
  getCachedResponse: store.getCachedResponse,
  queueMutation: store.queueMutation,
}));

// The network error is logged on its way through; keep that off the wire.
vi.mock('../errorLogger', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../errorLogger')>()),
  logError: vi.fn(),
  logApiError: vi.fn(),
}));

import { apiPost } from '../api';

const PATH = '/v1/boq/boqs/by-projects/';
const BODY = { project_ids: ['p-1', 'p-2'] };
const READ_KEY = `POST ${PATH} ${JSON.stringify(BODY)}`;

function goOffline() {
  vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))));
}

function answerOnline(body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })),
  );
}

beforeEach(() => {
  store.cacheResponse.mockClear();
  store.getCachedResponse.mockReset();
  store.getCachedResponse.mockResolvedValue(null);
  store.queueMutation.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('a POST that says it only reads', () => {
  it('is answered from the offline cache under its body, and never queued', async () => {
    goOffline();
    const cached = { 'p-1': [], 'p-2': [] };
    store.getCachedResponse.mockResolvedValue(cached);

    await expect(apiPost(PATH, BODY, { readOnly: true })).resolves.toEqual(cached);

    expect(store.getCachedResponse).toHaveBeenCalledWith(READ_KEY);
    expect(store.queueMutation).not.toHaveBeenCalled();
  });

  it('fails as a read fails when nothing is cached, rather than pretending it was saved', async () => {
    goOffline();

    await expect(apiPost(PATH, BODY, { readOnly: true })).rejects.toThrow('Failed to fetch');

    expect(store.queueMutation).not.toHaveBeenCalled();
  });

  it('caches its answer online under a key that carries the body', async () => {
    const answer = { 'p-1': [{ id: 'b-1' }], 'p-2': [] };
    answerOnline(answer);

    await expect(apiPost(PATH, BODY, { readOnly: true })).resolves.toEqual(answer);
    expect(store.cacheResponse).toHaveBeenCalledWith(READ_KEY, answer);

    // A different set of projects is a different question with its own entry.
    store.cacheResponse.mockClear();
    await apiPost(PATH, { project_ids: ['p-3'] }, { readOnly: true });
    expect(store.cacheResponse).toHaveBeenCalledWith(`POST ${PATH} ${JSON.stringify({ project_ids: ['p-3'] })}`, answer);
  });
});

describe('a POST that did not opt in', () => {
  it('is still queued offline for replay, as every change is', async () => {
    goOffline();

    await expect(apiPost('/v1/boq/boqs/', { name: 'Shell' })).resolves.toBeUndefined();

    expect(store.queueMutation).toHaveBeenCalledTimes(1);
    expect(store.queueMutation.mock.calls[0]?.[0]).toMatchObject({
      method: 'POST',
      path: '/v1/boq/boqs/',
      body: { name: 'Shell' },
    });
    expect(store.getCachedResponse).not.toHaveBeenCalled();
  });

  it('caches nothing when it succeeds online', async () => {
    answerOnline({ id: 'b-9' });

    await apiPost('/v1/boq/boqs/', { name: 'Shell' });

    expect(store.cacheResponse).not.toHaveBeenCalled();
  });
});

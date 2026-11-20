import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  calls: [] as string[],
  status: 200,
  body: {} as unknown,
}));

vi.mock('@/shared/lib/api', () => {
  class ApiError extends Error {
    constructor(public status: number, public statusText: string, public body: unknown) { super(statusText); }
  }
  const call = (method: string) => vi.fn(async (path: string, ...rest: unknown[]) => {
    const init = (method === 'GET' || method === 'DELETE' ? rest[0] : rest[1]) as { headers?: Record<string, string> } | undefined;
    api.calls.push(`${method} ${path} ${init?.headers?.['X-DDC-Link']}`);
    if (api.status >= 400) throw new ApiError(api.status, 'x', api.body);
    return api.body;
  });
  return {
    API_BASE: '/api', ApiError,
    apiGet: call('GET'), apiPost: call('POST'), apiPut: call('PUT'), apiDelete: call('DELETE'),
    fetchWithAuth: vi.fn(async (url: string, init: RequestInit = {}) => {
      const file = (init.body as FormData | undefined)?.get('package') as File | undefined;
      api.calls.push(`${init.method ?? 'GET'} ${url}${file ? ` ${file.name} ${file.size}` : ''}`);
      return new Response(JSON.stringify(api.body), { status: api.status, statusText: 'x' });
    }),
  };
});
vi.mock('./api', () => ({ LINK_VERSION: '1' }));

import { fetchDraft, makeRevision, putRights, saveDraft } from './draftApi';

beforeEach(() => {
  api.calls = [];
  api.status = 200;
  api.body = {};
});

describe('drafts of the browser editor', () => {
  it('autosave stores the package as the draft (no lock, no revision)', async () => {
    api.body = { revision_id: 'r', element_count: 3, estimate: { estimate: false, lines: [], model_total: '0' } };
    const d = await saveDraft('p1', new Uint8Array(22));
    expect(d.element_count).toBe(3);
    expect(api.calls).toEqual(['PUT /api/v1/design/projects/p1/draft draft.ddcrev 22']);
  });

  it('a refused package keeps its status and reason', async () => {
    api.status = 422;
    api.body = { detail: 'manifest: sha256 mismatch' };
    await expect(saveDraft('p1', new Uint8Array(22))).rejects.toMatchObject({ status: 422, body: { detail: 'manifest: sha256 mismatch' } });
  });

  it('no draft is null, other failures are thrown', async () => {
    api.status = 404;
    expect(await fetchDraft('p1')).toBeNull();
    api.status = 500;
    await expect(fetchDraft('p1')).rejects.toMatchObject({ status: 500 });
  });

  it('one action makes the revision; rights are per project', async () => {
    await makeRevision('p1');
    await putRights('p1', 'managers');
    expect(api.calls).toEqual(['POST /v1/design/projects/p1/draft/revision 1', 'PUT /v1/design/projects/p1/design-rights 1']);
  });
});

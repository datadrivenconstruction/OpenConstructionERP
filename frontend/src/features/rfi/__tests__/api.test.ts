// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Wave 8 (Tests) - URL-contract tests for the RFI api helpers.
 *
 * The exact request paths are load-bearing and have bitten us before:
 *   - ``getRFI`` / ``updateRFI`` MUST hit ``/v1/rfi/{id}`` with NO trailing
 *     slash. The app runs with ``redirect_slashes=False``, so a stray slash
 *     404s and the detail page shows "RFI not found" forever (the Wave 7 fix).
 *   - ``createVariationFromRFI`` MUST hit the trailing-slash form
 *     ``/v1/rfi/{id}/create-variation/`` for the same reason, inverted.
 *   - ``fetchRFIs`` must omit empty / whitespace-only filters from the query
 *     string (an empty ``?status=`` would 422 against the enum-validated
 *     param) and only include offset/limit when they are real numbers.
 *   - ``fetchRFIs`` must hand back the page envelope rather than unwrapping
 *     it to ``items``. The register is capped at 100 rows a page, so a caller
 *     that never sees ``total`` cannot say how much of it is on screen.
 *
 * We mock the shared HTTP layer so these are pure URL-assembly assertions
 * with no network and no coupling to the auth/toast/offline stores.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

const apiGet = vi.fn(async (..._args: unknown[]) => ({}) as unknown);
const apiPost = vi.fn(async (..._args: unknown[]) => ({}) as unknown);
const apiPatch = vi.fn(async (..._args: unknown[]) => ({}) as unknown);
const downloadWithAuth = vi.fn(async (..._args: unknown[]) => undefined);
let uiLanguage: string | null = 'en';

vi.mock('@/shared/lib/api', () => ({
  API_BASE: '/api',
  activeLanguageTag: () => uiLanguage,
  apiGet: (...args: unknown[]) => apiGet(...args),
  apiPost: (...args: unknown[]) => apiPost(...args),
  apiPatch: (...args: unknown[]) => apiPatch(...args),
  downloadWithAuth: (...args: unknown[]) => downloadWithAuth(...args),
}));

import {
  getRFI,
  fetchRFIs,
  fetchRFIStats,
  createRFI,
  updateRFI,
  respondToRFI,
  closeRFI,
  createVariationFromRFI,
  downloadRFIPdf,
  downloadRFIRegister,
} from '../api';

beforeEach(() => {
  apiGet.mockClear();
  apiPost.mockClear();
  apiPatch.mockClear();
  downloadWithAuth.mockClear();
  uiLanguage = 'en';
});

// Read the Nth positional arg of a mock's Mth call. `vi.fn` infers an
// empty-tuple call signature from a no-arg implementation and
// `noUncheckedIndexedAccess` makes `calls[m]` possibly-undefined, so index the
// recorded calls through this helper to keep the URL-contract assertions clean.
function nthArg(
  mock: { mock: { calls: unknown[][] } },
  call: number,
  arg: number,
): unknown {
  return mock.mock.calls[call]?.[arg];
}

describe('getRFI', () => {
  it('GETs /v1/rfi/{id} with NO trailing slash', async () => {
    await getRFI('abc-123');
    expect(apiGet).toHaveBeenCalledTimes(1);
    expect(nthArg(apiGet, 0, 0)).toBe('/v1/rfi/abc-123');
  });
});

describe('updateRFI', () => {
  it('PATCHes /v1/rfi/{id} with NO trailing slash and forwards the body', async () => {
    const body = { subject: 'New' };
    await updateRFI('abc-123', body);
    expect(apiPatch).toHaveBeenCalledTimes(1);
    expect(nthArg(apiPatch, 0, 0)).toBe('/v1/rfi/abc-123');
    expect(nthArg(apiPatch, 0, 1)).toEqual(body);
  });

  it('forwards a status transition (draft -> open) in the PATCH body', async () => {
    // The "Open RFI" affordance publishes a drafted RFI by PATCHing status.
    await updateRFI('abc-123', { status: 'open' });
    expect(nthArg(apiPatch, 0, 0)).toBe('/v1/rfi/abc-123');
    expect(nthArg(apiPatch, 0, 1)).toEqual({ status: 'open' });
  });
});

describe('downloadRFIPdf', () => {
  it('GETs the trailing-slash PDF route in the UI language', async () => {
    // The download bypasses apiGet and its Accept-Language header, so the
    // query parameter is the only thing that carries the reader's language.
    uiLanguage = 'de';
    await downloadRFIPdf('abc-123', 'RFI-007');
    expect(downloadWithAuth).toHaveBeenCalledTimes(1);
    expect(nthArg(downloadWithAuth, 0, 0)).toBe('/api/v1/rfi/abc-123/export/pdf/?locale=de');
    expect(nthArg(downloadWithAuth, 0, 1)).toBe('RFI-007.pdf');
  });

  it('leaves the language to the server when the UI has none yet', async () => {
    uiLanguage = null;
    await downloadRFIPdf('abc-123', '');
    expect(nthArg(downloadWithAuth, 0, 0)).toBe('/api/v1/rfi/abc-123/export/pdf/');
    expect(nthArg(downloadWithAuth, 0, 1)).toBe('rfi.pdf');
  });

  it('prints the form in the language the caller names, over the UI language', async () => {
    // The form is sent to people who do not read the sender's language.
    uiLanguage = 'tr';
    await downloadRFIPdf('abc-123', 'RFI-007', 'en');
    expect(nthArg(downloadWithAuth, 0, 0)).toBe('/api/v1/rfi/abc-123/export/pdf/?locale=en');
  });
});

describe('downloadRFIRegister', () => {
  it('GETs the localized register route, not the English-only /export/', async () => {
    await downloadRFIRegister('p 1', 'xlsx', 'tr');
    expect(downloadWithAuth).toHaveBeenCalledTimes(1);
    expect(nthArg(downloadWithAuth, 0, 0)).toBe(
      '/api/v1/rfi/export/register/?project_id=p+1&format=xlsx&locale=tr',
    );
  });
});

describe('createVariationFromRFI', () => {
  it('POSTs the trailing-slash create-variation route', async () => {
    await createVariationFromRFI('abc-123');
    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(nthArg(apiPost, 0, 0)).toBe('/v1/rfi/abc-123/create-variation/');
  });
});

describe('respondToRFI / closeRFI', () => {
  it('respondToRFI POSTs the trailing-slash respond route with the body', async () => {
    await respondToRFI('r1', { official_response: 'done' });
    expect(nthArg(apiPost, 0, 0)).toBe('/v1/rfi/r1/respond/');
    expect(nthArg(apiPost, 0, 1)).toEqual({ official_response: 'done' });
  });

  it('closeRFI POSTs the trailing-slash close route', async () => {
    await closeRFI('r1');
    expect(nthArg(apiPost, 0, 0)).toBe('/v1/rfi/r1/close/');
  });
});

describe('createRFI', () => {
  it('POSTs the collection root with a trailing slash', async () => {
    await createRFI({ project_id: 'p1', subject: 's', question: 'q' });
    expect(nthArg(apiPost, 0, 0)).toBe('/v1/rfi/');
  });
});

describe('fetchRFIStats', () => {
  it('encodes the project id into the stats query', async () => {
    await fetchRFIStats('p1/2');
    expect(nthArg(apiGet, 0, 0)).toBe('/v1/rfi/stats/?project_id=p1%2F2');
  });
});

describe('fetchRFIs query-string assembly', () => {
  it('returns the bare collection root when no filters are supplied', async () => {
    apiGet.mockResolvedValueOnce({ items: [], total: 0, offset: 0, limit: 50 });
    const page = await fetchRFIs();
    expect(nthArg(apiGet, 0, 0)).toBe('/v1/rfi/');
    expect(page.items).toEqual([]);
  });

  it('hands back the page envelope whole, total included', async () => {
    // The register endpoint caps `limit` at 100, so on a busy project the
    // rows are always a slice. Collapsing the reply to `items` here would
    // put every caller back to guessing how much of the register it holds.
    apiGet.mockResolvedValueOnce({
      items: [{ id: 'r1' }, { id: 'r2' }],
      total: 341,
      offset: 0,
      limit: 100,
    });
    const page = await fetchRFIs({ project_id: 'p1', limit: 100 });
    expect(page.items.map((r) => r.id)).toEqual(['r1', 'r2']);
    expect(page.total).toBe(341);
    expect(page.limit).toBe(100);
  });

  it('omits empty status and whitespace-only search', async () => {
    await fetchRFIs({ project_id: 'p1', status: '', search: '   ' });
    const url = nthArg(apiGet, 0, 0) as string;
    expect(url).toContain('project_id=p1');
    expect(url).not.toContain('status=');
    expect(url).not.toContain('search=');
  });

  it('includes status, trimmed search, offset and limit when present', async () => {
    await fetchRFIs({
      project_id: 'p1',
      status: 'open',
      search: '  rebar  ',
      offset: 20,
      limit: 50,
    });
    const url = nthArg(apiGet, 0, 0) as string;
    const qs = new URLSearchParams(url.split('?')[1]);
    expect(qs.get('project_id')).toBe('p1');
    expect(qs.get('status')).toBe('open');
    expect(qs.get('search')).toBe('rebar');
    expect(qs.get('offset')).toBe('20');
    expect(qs.get('limit')).toBe('50');
  });

  it('includes offset=0 (a real number, not falsy-dropped)', async () => {
    await fetchRFIs({ project_id: 'p1', offset: 0 });
    const qs = new URLSearchParams(
      (nthArg(apiGet, 0, 0) as string).split('?')[1],
    );
    // offset 0 is meaningful (first page) and must survive the typeof check.
    expect(qs.get('offset')).toBe('0');
  });
});

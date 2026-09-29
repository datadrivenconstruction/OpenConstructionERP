// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Path tests for the RFQ bidding client.
//
// The application is built with redirect_slashes=False, so /rfq-bidding/{id}/issue
// and /rfq-bidding/{id}/issue/ are two different URLs and only the second is
// served. These calls were written without the slash and every one of them
// answered 404: issuing an RFQ, validating it, reading and adding scope lines,
// reading the award, submitting a bid, evaluating and awarding it. The bid list
// and the comparison are held back on purpose, see their comments in api.ts.
// The component tests stub this module whole and cannot see the URL, which is
// why the paths are pinned here.

import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/shared/lib/api')>()),
  apiGet: vi.fn(() => Promise.resolve({ items: [], total: 0 })),
  apiPost: vi.fn(() => Promise.resolve({})),
  apiPatch: vi.fn(() => Promise.resolve({})),
  apiDelete: vi.fn(() => Promise.resolve(undefined)),
}));

import { apiGet, apiPost } from '@/shared/lib/api';
import {
  issueRFQ,
  validateRFQ,
  fetchScopeLines,
  addScopeLine,
  fetchAward,
  submitBid,
  evaluateBid,
  awardBid,
} from '../api';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('RFQ bidding routes carry the trailing slash the server declares', () => {
  it('issues and validates an RFQ', async () => {
    await issueRFQ('r-1');
    expect(apiPost).toHaveBeenCalledWith('/v1/rfq-bidding/r-1/issue/');
    await validateRFQ('r-1');
    expect(apiGet).toHaveBeenCalledWith('/v1/rfq-bidding/r-1/validate/');
  });

  it('reads and adds scope lines, unwrapping the server page', async () => {
    vi.mocked(apiGet).mockResolvedValueOnce({ items: [{ id: 'l-1' }], total: 1 });
    const lines = await fetchScopeLines('r-1');
    expect(apiGet).toHaveBeenCalledWith('/v1/rfq-bidding/r-1/lines/');
    expect(lines).toEqual([{ id: 'l-1' }]);
    await addScopeLine('r-1', { description: 'Concrete', quantity: 1, unit: 'm3' } as never);
    expect(apiPost).toHaveBeenCalledWith('/v1/rfq-bidding/r-1/lines/', expect.anything());
  });

  it('reads the award', async () => {
    await fetchAward('r-1');
    expect(apiGet).toHaveBeenCalledWith('/v1/rfq-bidding/r-1/award/');
  });

  it('submits, evaluates and awards a bid', async () => {
    await submitBid({ rfq_id: 'r-1', vendor_name: 'A', total_amount: 1 });
    expect(apiPost).toHaveBeenCalledWith('/v1/rfq-bidding/bids/', expect.anything());
    await evaluateBid('b-1');
    expect(apiPost).toHaveBeenCalledWith('/v1/rfq-bidding/bids/b-1/evaluate/');
    await awardBid('b-1');
    expect(apiPost).toHaveBeenCalledWith('/v1/rfq-bidding/bids/b-1/award/');
  });
});

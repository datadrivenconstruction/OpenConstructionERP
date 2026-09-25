// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The cost search serves ``rate`` as a Decimal string ("4465.43"). The
// "From Database" modal tests ``typeof item.rate === 'number'`` to decide
// whether a row is priced, so a string rate flagged every priced row with a
// false "No rate" badge and zeroed the selection preview. The fetcher is the
// one boundary every consumer goes through, so the coercion lives there.

import { describe, it, expect, vi } from 'vitest';

vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(async () => ({
    items: [
      { id: 'a', code: 'A', description: 'Frame wall', unit: 'm2', rate: '4465.43', region: 'US_USA', classification: {}, components: [] },
      { id: 'b', code: 'B', description: 'Unpriced', unit: 'm2', rate: null, region: 'US_USA', classification: {}, components: [] },
      { id: 'c', code: 'C', description: 'Already numeric', unit: 'm2', rate: 12.5, region: 'US_USA', classification: {}, components: [] },
    ],
    next_cursor: null,
    has_more: false,
    total: 3,
  })),
  apiPost: vi.fn(),
  apiPut: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  downloadWithAuth: vi.fn(),
  API_BASE: '/api',
}));

import { fetchCostSearch } from '../api';

describe('fetchCostSearch', () => {
  it('hands the rate over as a number, whatever the wire shape', async () => {
    const page = await fetchCostSearch({ q: 'frame walls' });
    const rates = page.items.map((i) => i.rate);
    expect(rates).toEqual([4465.43, 0, 12.5]);
    for (const r of rates) expect(typeof r).toBe('number');
  });
});

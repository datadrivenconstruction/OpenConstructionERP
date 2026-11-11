import { describe, it, expect, vi, beforeEach } from 'vitest';

const apiPost = vi.fn();
vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(),
  apiPut: vi.fn(),
  apiPost: (...args: unknown[]) => apiPost(...args),
}));

import { createOwnMaterial, isDecimalString } from './api';

describe('own material quick form', () => {
  beforeEach(() => apiPost.mockReset());

  it('accepts plain decimals and biogenic credits, rejects junk', () => {
    expect(isDecimalString('180.5')).toBe(true);
    expect(isDecimalString('-1.2')).toBe(true);
    expect(isDecimalString(' 42 ')).toBe(true);
    expect(isDecimalString('')).toBe(false);
    expect(isDecimalString('1,5')).toBe(false);
    expect(isDecimalString('abc')).toBe(false);
  });

  it('saves a custom EPD record with the GWP kept as a decimal string', async () => {
    apiPost.mockResolvedValue({ id: 'x', epd_id: 'own-x' });
    await createOwnMaterial({ name: 'Recycled concrete C30/37', category: 'concrete', unit: 'm3', gwp: '180.5' });
    const [url, body] = apiPost.mock.calls[0] as [string, Record<string, unknown>];
    expect(url).toBe('/v1/carbon/epd');
    expect(body).toMatchObject({
      source: 'custom',
      material_class: 'concrete',
      product_name: 'Recycled concrete C30/37',
      declared_unit: 'm3',
      gwp_a1a3: '180.5',
    });
    expect(String(body.epd_id)).toMatch(/^own-recycled-concrete-c30-37-[a-z0-9]+$/);
  });
});

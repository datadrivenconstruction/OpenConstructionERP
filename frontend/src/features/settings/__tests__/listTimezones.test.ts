import { afterEach, describe, expect, it, vi } from 'vitest';
import { listTimezones } from '../RegionalSettings';

describe('listTimezones', () => {
  afterEach(() => vi.restoreAllMocks());

  it('offers every IANA zone the runtime knows, UTC first', () => {
    const zones = listTimezones();
    expect(zones[0]).toBe('UTC');
    expect(zones).toContain('America/Santo_Domingo');
    expect(zones).toContain('Africa/Lagos');
    expect(zones.filter((z) => z === 'UTC')).toHaveLength(1);
  });

  it('falls back to the short list when Intl cannot enumerate zones', () => {
    vi.spyOn(Intl as unknown as { supportedValuesOf: () => string[] }, 'supportedValuesOf').mockImplementation(() => {
      throw new RangeError('unsupported');
    });
    const zones = listTimezones();
    expect(zones[0]).toBe('UTC');
    expect(zones).toContain('Europe/Berlin');
  });
});

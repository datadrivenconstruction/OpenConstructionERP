import { describe, expect, it } from 'vitest';
import { healScope, isCatalogueRegionTag, scopeKey } from './scopeSync';

describe('costs scope sync', () => {
  const names = ['Retailer prices', 'My rates'];

  it('treats a catalogue-named region tag as All', () => {
    expect(healScope({ region: 'Retailer prices', catalogId: '' }, names)).toEqual({ region: '', catalogId: '' });
  });

  it('keeps a real region and drops the region when a catalogue is chosen', () => {
    expect(healScope({ region: 'DE_BERLIN', catalogId: '' }, names)).toEqual({ region: 'DE_BERLIN', catalogId: '' });
    expect(healScope({ region: 'DE_BERLIN', catalogId: 'c1' }, names)).toEqual({ region: '', catalogId: 'c1' });
  });

  it('empty region is never a catalogue tag, and keys differ per catalogue', () => {
    expect(isCatalogueRegionTag('', names)).toBe(false);
    expect(scopeKey({ region: '', catalogId: '' })).not.toEqual(scopeKey({ region: '', catalogId: 'c1' }));
  });
});

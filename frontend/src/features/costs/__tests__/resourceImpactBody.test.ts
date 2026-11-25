import { describe, expect, it } from 'vitest';

import { buildChangeBody, resourceImpactApi } from '../ResourceImpactDialog';

const row = { resource_key: 'CEM-1', resource_name: 'Cement CEM I', unit_price: '100.00' };

describe('buildChangeBody', () => {
  it('sends only the fields that change', () => {
    expect(buildChangeBody(row, '120', 'Cement CEM I')).toEqual({
      resource_key: 'CEM-1',
      new_unit_price: '120',
    });
    expect(buildChangeBody(row, '100.00', ' Cement CEM I 42.5 ')).toEqual({
      resource_key: 'CEM-1',
      new_name: 'Cement CEM I 42.5',
    });
  });

  it('sends nothing to change when nothing changed, so the server reports it', () => {
    expect(buildChangeBody(row, '100.00', 'Cement CEM I')).toEqual({ resource_key: 'CEM-1' });
  });

  it('exposes preview and apply as separate calls', () => {
    expect(typeof resourceImpactApi.preview).toBe('function');
    expect(typeof resourceImpactApi.apply).toBe('function');
  });
});

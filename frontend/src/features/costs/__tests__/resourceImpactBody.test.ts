import { describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/shared/lib/api';

import {
  applyRefusalCode,
  buildChangeBody,
  invalidateAfterApply,
  resourceImpactApi,
} from '../ResourceImpactDialog';

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

describe('apply refusal and refresh', () => {
  it('reads the refusal code from a 409 only', () => {
    const body = { detail: { code: 'resource.change.stale_preview', message: 'x' } };
    expect(applyRefusalCode(new ApiError(409, 'Conflict', body))).toBe('resource.change.stale_preview');
    expect(applyRefusalCode(new ApiError(500, 'Error', body))).toBeNull();
    expect(applyRefusalCode(new Error('x'))).toBeNull();
  });

  it('invalidates every costs query after apply', () => {
    const invalidateQueries = vi.fn();
    invalidateAfterApply({ invalidateQueries });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ['costs'] });
  });
});

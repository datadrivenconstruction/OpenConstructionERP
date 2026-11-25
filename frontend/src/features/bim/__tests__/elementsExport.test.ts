import { describe, expect, it } from 'vitest';
import { elementsExportQuery } from '../api';

describe('elementsExportQuery', () => {
  it('is empty without filters', () => {
    expect(elementsExportQuery()).toBe('');
  });
  it('adds only the filters that are set', () => {
    expect(elementsExportQuery({ storey: 'L1', discipline: '' })).toBe('?storey=L1');
  });
});

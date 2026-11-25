import { describe, expect, it } from 'vitest';
import { elementsExportPath } from '../api';

describe('elementsExportPath', () => {
  it('has no trailing slash and a format suffix', () => {
    expect(elementsExportPath('m-1', 'csv')).toMatch(/\/v1\/bim_hub\/models\/m-1\/export\/elements\.csv$/);
  });
  it('adds only the filters that are set', () => {
    const p = elementsExportPath('m-1', 'json', { storey: 'L1', discipline: '' });
    expect(p).toMatch(/elements\.json\?storey=L1$/);
  });
});

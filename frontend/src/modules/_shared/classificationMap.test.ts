import { describe, it, expect } from 'vitest';
import {
  CLASSIFICATION_MAP,
  lookupClassification,
  mapClassification,
} from './classificationMap';

describe('CLASSIFICATION_MAP', () => {
  it('should contain at least 20 mappings', () => {
    expect(CLASSIFICATION_MAP.length).toBeGreaterThanOrEqual(20);
  });

  it('every entry should have a description', () => {
    for (const m of CLASSIFICATION_MAP) {
      expect(m.description).toBeTruthy();
    }
  });

  it('every entry should have at least one classification code', () => {
    for (const m of CLASSIFICATION_MAP) {
      const hasCodes = m.din276 || m.nrm || m.masterformat || m.lots || m.acmm;
      expect(hasCodes).toBeTruthy();
    }
  });
});

describe('lookupClassification', () => {
  it('should find by DIN 276 code', () => {
    const result = lookupClassification('din276', '330');
    expect(result).toBeDefined();
    expect(result!.nrm).toBe('2.1');
    expect(result!.masterformat).toBe('03 30 00');
  });

  it('should find by NRM code', () => {
    const result = lookupClassification('nrm', '5.1');
    expect(result).toBeDefined();
    expect(result!.din276).toBe('410');
  });

  it('should find by MasterFormat code', () => {
    const result = lookupClassification('masterformat', '26 00 00');
    expect(result).toBeDefined();
    expect(result!.din276).toBe('440');
  });

  it('should return undefined for unknown code', () => {
    expect(lookupClassification('din276', '999')).toBeUndefined();
  });
});

describe('mapClassification', () => {
  it('should map DIN 276 to NRM', () => {
    expect(mapClassification('din276', 'nrm', '330')).toBe('2.1');
  });

  it('should map NRM to MasterFormat', () => {
    expect(mapClassification('nrm', 'masterformat', '5.6')).toBe('26 00 00');
  });

  it('should map DIN 276 to French Lots', () => {
    expect(mapClassification('din276', 'lots', '350')).toBe('Lot 3');
  });

  it('should map to ACMM', () => {
    expect(mapClassification('din276', 'acmm', '440')).toBe('F');
  });

  it('should return undefined for unknown mapping', () => {
    expect(mapClassification('din276', 'nrm', '999')).toBeUndefined();
  });
});

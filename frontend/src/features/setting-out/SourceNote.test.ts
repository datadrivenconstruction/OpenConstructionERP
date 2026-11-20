// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { sourceText, splitReference } from './SourceNote';

describe('tolerance source text', () => {
  it('adds the clause once', () => {
    expect(sourceText('GB 50204, 2015', 'Table 8.3.2')).toBe('GB 50204, 2015, Table 8.3.2');
    expect(sourceText('GB 50204, 2015; Table 8.3.2', 'Table 8.3.2')).toBe('GB 50204, 2015; Table 8.3.2');
    expect(sourceText('Demo values, not a standard')).toBe('Demo values, not a standard');
    expect(sourceText('', 'cl. 4')).toBe('cl. 4');
  });

  it('splits the status a request stored after its reference', () => {
    expect(splitReference('ACI 117, 2010; 4.1; to_verify')).toEqual({ text: 'ACI 117, 2010; 4.1', status: 'to_verify' });
    expect(splitReference('GB 50204, 2015; Table 8.3.2; verified')).toEqual({ text: 'GB 50204, 2015; Table 8.3.2', status: 'verified' });
    expect(splitReference('Demo values, not a standard')).toEqual({ text: 'Demo values, not a standard', status: '' });
    expect(splitReference(undefined)).toEqual({ text: '', status: '' });
  });
});

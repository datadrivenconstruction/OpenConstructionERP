// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { placeholderFromConverterWithoutMesh } from '../placeholderGeometry';

describe('placeholderFromConverterWithoutMesh', () => {
  it('is true only when the converter ran without writing a mesh', () => {
    expect(placeholderFromConverterWithoutMesh({ placeholder_reason: 'converter_no_mesh' })).toBe(true);
    expect(placeholderFromConverterWithoutMesh({ placeholder_reason: 'converter_missing' })).toBe(false);
    expect(placeholderFromConverterWithoutMesh({ placeholder_reason: 'converter_failed' })).toBe(false);
    expect(placeholderFromConverterWithoutMesh({})).toBe(false);
    expect(placeholderFromConverterWithoutMesh(null)).toBe(false);
  });
});

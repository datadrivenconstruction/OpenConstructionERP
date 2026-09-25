// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { regionOptionLabel } from './regionLabel';

// P-55: a Croatian estimator looked for "Hrvatska" in the region list and
// found only the English "Croatia".
describe('regionOptionLabel', () => {
  const croatia = { value: 'Croatia', label: 'Croatia', iso: 'HR' };

  it('names a single-country region in the reader language', () => {
    expect(regionOptionLabel(croatia, 'hr')).toBe('Hrvatska');
    expect(regionOptionLabel(croatia, 'de')).toBe('Kroatien');
    expect(regionOptionLabel(croatia, 'en')).toBe('Croatia');
  });

  it('keeps the label of a grouping that is not one country', () => {
    const dach = { value: 'DACH', label: 'DACH (Germany, Austria, Switzerland)' };
    expect(regionOptionLabel(dach, 'hr')).toBe('DACH (Germany, Austria, Switzerland)');
  });

  it('falls back to the label for an unknown language tag', () => {
    expect(regionOptionLabel(croatia, '')).toBe('Croatia');
  });
});

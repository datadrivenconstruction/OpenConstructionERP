// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The VAT placeholder Project Settings shows beside the override field.
//
// Ireland was added as a region of its own and had no suggestion, so its
// settings showed 0%. Its suggestion is the 13.5% construction rate the server
// seeds a bill with, and the percentage has to survive being displayed: a
// whole-number rounding printed 14, and 0.135 * 100 is not exactly 13.5.

import { describe, it, expect } from 'vitest';
import { getVatPercent, getVatRate } from './boqHelpers';

describe('VAT suggestion for a region', () => {
  it('suggests the Irish construction rate, not the standard 23 or the UK 20', () => {
    expect(getVatRate('Ireland')).toBe(0.135);
    expect(getVatPercent('Ireland')).toBe(13.5);
  });

  it('keeps whole-number rates whole', () => {
    expect(getVatPercent('DACH (Germany, Austria, Switzerland)')).toBe(19);
    expect(getVatPercent('United Kingdom')).toBe(20);
  });

  it('suggests nothing for a region it does not know', () => {
    expect(getVatPercent(undefined)).toBe(0);
    expect(getVatPercent('Atlantis')).toBe(0);
  });
});

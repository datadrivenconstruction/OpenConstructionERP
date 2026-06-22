/**
 * Regression test for Monte Carlo histogram bin labels (audit #16).
 *
 * The backend serialises every Decimal money value as a JSON *string*
 * (e.g. "100000.00"). The histogram-bin midpoint label was computed as
 * ``(b.lower + b.upper) / 2`` directly on those wire values, so the binary
 * ``+`` string-concatenated ("100000.00" + "150000.00") and ``/ 2`` then
 * yielded ``NaN`` — every bar on the "Contingency distribution" chart was
 * labelled "NaN". ``binMidpointLabel`` now coerces both bounds with
 * ``Number()`` before the addition. These tests fail on the original code
 * and pass after the fix.
 */
import { describe, it, expect } from 'vitest';

import { binMidpointLabel } from './MonteCarloTab';
import type { RiskHistogramBin } from './api';

/** Pull the numeric value back out of a formatted label for assertions. */
function parseLabelNumber(label: string): number {
  // Strip everything that is not a digit, sign or decimal separator. The
  // grouping separator is locale-dependent; under the UTC/en test locale it
  // is a comma, which we remove here.
  const cleaned = label.replace(/[^0-9.-]/g, '');
  return Number(cleaned);
}

describe('binMidpointLabel (Monte Carlo histogram)', () => {
  it('produces a finite midpoint from Decimal-as-string bounds (no NaN)', () => {
    // The shape the wire actually delivers: Decimal rendered as a string.
    const bin = { lower: '100000.00', upper: '150000.00' } as unknown as RiskHistogramBin;

    const label = binMidpointLabel(bin, 'EUR');

    expect(label).not.toBe('NaN');
    expect(label.includes('NaN')).toBe(false);
    // Midpoint of 100000 and 150000 is 125000.
    expect(parseLabelNumber(label)).toBe(125000);
    expect(Number.isFinite(parseLabelNumber(label))).toBe(true);
  });

  it('also handles genuine numeric bounds', () => {
    const bin = { lower: 200, upper: 600 } as unknown as RiskHistogramBin;

    const label = binMidpointLabel(bin, '');

    expect(label.includes('NaN')).toBe(false);
    expect(parseLabelNumber(label)).toBe(400);
  });

  it('renders a currency-less grouped number when currency is unknown', () => {
    const bin = { lower: '1000.00', upper: '3000.00' } as unknown as RiskHistogramBin;

    // Blank currency must not throw and must not leak "NaN".
    const label = binMidpointLabel(bin, '');

    expect(label.includes('NaN')).toBe(false);
    expect(parseLabelNumber(label)).toBe(2000);
  });
});

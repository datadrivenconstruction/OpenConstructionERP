// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Tests for the pure labor-rate editor helpers in ./api. These are the
// frontend's own responsibilities (shaping the compute request, seeding rows,
// sanitising money/percentage text, defensively normalising the wire
// response); the Decimal arithmetic itself is proven server-side.

import { describe, it, expect, vi } from 'vitest';

// The pure helpers never touch the network, so stub the API client to keep the
// module graph light and the test hermetic.
vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

import {
  newOnCost,
  newCrewMember,
  normalizeAmount,
  normalizeCount,
  isPositiveAmount,
  canSaveTemplate,
  buildComputeRequest,
  normalizeRateBreakdown,
  type RateBreakdown,
} from './api';

describe('newOnCost / newCrewMember', () => {
  it('defaults a fresh on-cost to a blank percentage row with a unique key', () => {
    const a = newOnCost();
    const b = newOnCost();
    expect(a.label).toBe('');
    expect(a.kind).toBe('percentage');
    expect(a.value).toBe('');
    expect(a.key).not.toBe(b.key);
  });

  it('seeds an on-cost with the given label and kind', () => {
    const row = newOnCost('Small tools', 'fixed', '1.5');
    expect(row.label).toBe('Small tools');
    expect(row.kind).toBe('fixed');
    expect(row.value).toBe('1.5');
  });

  it('defaults a fresh crew member to one person with a unique key', () => {
    const a = newCrewMember();
    const b = newCrewMember();
    expect(a.trade).toBe('');
    expect(a.count).toBe(1);
    expect(a.all_in_rate).toBe('');
    expect(a.key).not.toBe(b.key);
  });
});

describe('normalizeAmount', () => {
  it('passes an exact decimal string through verbatim (no float rounding)', () => {
    expect(normalizeAmount('12.5')).toBe('12.5');
    expect(normalizeAmount('1234567.89')).toBe('1234567.89');
    expect(normalizeAmount('-5.25')).toBe('-5.25');
  });

  it('trims surrounding whitespace', () => {
    expect(normalizeAmount('  30 ')).toBe('30');
  });

  it('collapses blank to 0', () => {
    expect(normalizeAmount('')).toBe('0');
    expect(normalizeAmount('   ')).toBe('0');
  });

  it('sanitises unparseable input to 0 (never NaN)', () => {
    expect(normalizeAmount('abc')).toBe('0');
    expect(normalizeAmount('12.34.56')).toBe('0');
  });

  // '1,5' used to be asserted here as '0'. It is not unparseable input, it is
  // one and a half written the way most of the countries this product ships a
  // language for write it, and zeroing it silently zeroed every rate computed
  // from the base wage.
  it('reads a decimal comma as a decimal, not as garbage', () => {
    expect(normalizeAmount('1,5')).toBe('1.5');
    expect(normalizeAmount('30,50')).toBe('30.50');
    expect(normalizeAmount('1.234,56')).toBe('1234.56');
    expect(normalizeAmount('1,234.56')).toBe('1234.56');
  });
});

describe('normalizeCount', () => {
  it('keeps a positive integer', () => {
    expect(normalizeCount(3)).toBe(3);
  });

  it('truncates a fractional count', () => {
    expect(normalizeCount(3.9)).toBe(3);
  });

  it('clamps negatives and non-finite to 0', () => {
    expect(normalizeCount(-2)).toBe(0);
    expect(normalizeCount(Number.NaN)).toBe(0);
    expect(normalizeCount(0)).toBe(0);
  });
});

describe('isPositiveAmount', () => {
  it('accepts an amount above zero, trimmed', () => {
    expect(isPositiveAmount('28.50')).toBe(true);
    expect(isPositiveAmount('  0.01  ')).toBe(true);
  });

  it('rejects blank, zero and negative wages', () => {
    expect(isPositiveAmount('')).toBe(false);
    expect(isPositiveAmount('   ')).toBe(false);
    expect(isPositiveAmount('0')).toBe(false);
    expect(isPositiveAmount('0.00')).toBe(false);
    expect(isPositiveAmount('-5')).toBe(false);
  });

  it('rejects text that does not read as a number', () => {
    expect(isPositiveAmount('abc')).toBe(false);
  });
});

describe('canSaveTemplate', () => {
  const ready = { templateName: 'Bricklayer all-in', baseWage: '28.50', pending: false };

  it('allows a save when the template is named and the wage is positive', () => {
    expect(canSaveTemplate(ready)).toBe(true);
  });

  it('refuses a save while one is in flight', () => {
    expect(canSaveTemplate({ ...ready, pending: true })).toBe(false);
  });

  it('refuses an unnamed template', () => {
    expect(canSaveTemplate({ ...ready, templateName: '' })).toBe(false);
    expect(canSaveTemplate({ ...ready, templateName: '   ' })).toBe(false);
  });

  // The blank field is the reported case: buildComputeRequest turns it into
  // '0' for the preview, and the server refuses a base wage of zero.
  it('refuses a blank or zero base wage, which the server answers with a 422', () => {
    expect(canSaveTemplate({ ...ready, baseWage: '' })).toBe(false);
    expect(canSaveTemplate({ ...ready, baseWage: '0' })).toBe(false);
    expect(normalizeAmount('')).toBe('0');
  });
});

describe('buildComputeRequest', () => {
  it('drops empty rows, trims text, sanitises amounts and counts', () => {
    const req = buildComputeRequest({
      base_wage: ' 30 ',
      currency: ' eur ',
      onCosts: [
        newOnCost('Statutory', 'percentage', '20'),
        newOnCost('   ', 'fixed', '5'), // blank label -> dropped
        newOnCost('Tools', 'fixed', ' 1.50 '),
      ],
      crew: [
        newCrewMember('Mason', 2, '40'),
        newCrewMember('', 1, '10'), // blank trade -> dropped
        newCrewMember('Helper', 3.9, '25'), // count truncates to 3
      ],
    });

    expect(req.base_wage).toBe('30');
    expect(req.currency).toBe('eur');
    expect(req.components).toEqual([
      { label: 'Statutory', kind: 'percentage', value: '20' },
      { label: 'Tools', kind: 'fixed', value: '1.50' },
    ]);
    expect(req.crew).toEqual([
      { trade: 'Mason', count: 2, all_in_rate: '40' },
      { trade: 'Helper', count: 3, all_in_rate: '25' },
    ]);
  });

  it('maps a blank base wage to 0', () => {
    const req = buildComputeRequest({ base_wage: '', currency: '', onCosts: [], crew: [] });
    expect(req.base_wage).toBe('0');
    expect(req.components).toEqual([]);
    expect(req.crew).toEqual([]);
  });
});

describe('normalizeRateBreakdown', () => {
  it('keeps money as strings and leaves a null crew null', () => {
    const raw: RateBreakdown = {
      base_wage: '30',
      currency: 'EUR',
      percentage_total: '6',
      fixed_total: '1.5',
      all_in_rate: '37.5',
      lines: [
        { label: 'Statutory', kind: 'percentage', value: '20', amount: '6', subtotal: '36' },
      ],
      crew: null,
    };
    const out = normalizeRateBreakdown(raw);
    expect(out.all_in_rate).toBe('37.5');
    expect(typeof out.all_in_rate).toBe('string');
    expect(out.lines).toHaveLength(1);
    expect(out.crew).toBeNull();
  });

  it('defaults missing lines/crew so the UI never indexes undefined', () => {
    const raw = {
      base_wage: '30',
      currency: 'EUR',
      percentage_total: '0',
      fixed_total: '0',
      all_in_rate: '30',
    } as unknown as RateBreakdown;
    const out = normalizeRateBreakdown(raw);
    expect(out.lines).toEqual([]);
    expect(out.crew).toBeNull();
  });

  it('coerces crew headcount/count to numbers and keeps money as strings', () => {
    const raw: RateBreakdown = {
      base_wage: '30',
      currency: 'EUR',
      percentage_total: '0',
      fixed_total: '0',
      all_in_rate: '30',
      lines: [],
      crew: {
        currency: 'EUR',
        headcount: 3,
        total_cost_per_hour: '105',
        blended_hourly_rate: '35',
        members: [{ trade: 'Mason', count: 2, all_in_rate: '40', line_cost: '80' }],
      },
    };
    const out = normalizeRateBreakdown(raw);
    expect(out.crew?.headcount).toBe(3);
    expect(out.crew?.members[0]?.count).toBe(2);
    expect(out.crew?.blended_hourly_rate).toBe('35');
    expect(typeof out.crew?.total_cost_per_hour).toBe('string');
  });
});

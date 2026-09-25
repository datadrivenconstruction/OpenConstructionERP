// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import type { TFunction } from 'i18next';
import { awardRatesMessage } from '../awardRates';

// Echo the key and the interpolation, so the test reads which sentence was
// chosen and with what number.
const t = ((key: string, opts?: Record<string, unknown>) =>
  opts && 'n' in opts ? `${key}:${String(opts.n)}` : key) as unknown as TFunction;

const base = { package_id: 'p', bid_id: 'b', boq_id: 'q' };

describe('awardRatesMessage', () => {
  it('counts the positions an award wrote', () => {
    expect(awardRatesMessage({ ...base, positions_updated: 7, rates_skipped_reason: null }, t)).toBe(
      'tendering.award_rates_written:7',
    );
  });

  it('says a locked bill was left as approved', () => {
    expect(awardRatesMessage({ ...base, positions_updated: 0, rates_skipped_reason: 'boq_locked' }, t)).toBe(
      'tendering.award_rates_locked',
    );
  });

  it('says a lump-sum bid had no rates to write', () => {
    expect(awardRatesMessage({ ...base, positions_updated: 0, rates_skipped_reason: 'no_line_rates' }, t)).toBe(
      'tendering.award_rates_lump_sum',
    );
  });
});

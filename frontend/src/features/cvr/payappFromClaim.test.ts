import { describe, expect, it } from 'vitest';
import type { ProgressClaimOption } from './api';
import { payappDraftFromClaim, progressClaimLabel } from './payappFromClaim';

const claim: ProgressClaimOption = {
  id: 'c1',
  contract_id: 'k1',
  contract_code: 'MC-01',
  claim_number: 'PC-003',
  status: 'certified',
  period: '2026-08',
  gross_amount: '40000.00',
  retention_amount: '2000.00',
  net_due: '38000.00',
  currency: 'EUR',
};

describe('payappDraftFromClaim', () => {
  it('takes the period figures of the claim', () => {
    expect(payappDraftFromClaim(claim, '2026-09')).toEqual({
      period: '2026-08',
      number: 'PC-003',
      gross: '40000.00',
      retention: '2000.00',
    });
  });

  it('keeps the form period when the claim has none', () => {
    expect(payappDraftFromClaim({ ...claim, period: null }, '2026-09').period).toBe('2026-09');
  });
});

describe('progressClaimLabel', () => {
  it('joins what is known and skips what is not', () => {
    expect(progressClaimLabel(claim)).toBe('MC-01 · PC-003 · 2026-08');
    expect(progressClaimLabel({ ...claim, contract_code: '', period: null })).toBe('PC-003');
  });
});

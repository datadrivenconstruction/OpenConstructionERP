// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { ApiError } from '@/shared/lib/api';
import { emptyTerms, gateOfError, ruleKey, termsFromRound, type NegotiationRound } from '../awardTerms';

const round: NegotiationRound = {
  id: 'r2',
  package_id: 'p',
  bid_id: 'b',
  round_no: 2,
  pricing_mode: 'lump_sum',
  lines_total: '268450.00',
  lump_sum: '255000.00',
  discount_percent: '0',
  offer_total: '255000.00',
  contract_sum: '255000.00',
  note: '',
  is_final: true,
  approved_by: null,
  approved_at: null,
  created_at: null,
};

describe('award terms helpers', () => {
  it('starts a bid with nothing agreed', () => {
    expect(emptyTerms('b')).toMatchObject({ bid_id: 'b', discount_percent: '0', lump_sum: null, round_id: null });
  });

  it('takes the lump sum of a lump-sum round and drops it for a unit-price round', () => {
    const base = { ...emptyTerms('b'), retention_percent: '10' };
    expect(termsFromRound(base, round)).toMatchObject({ round_id: 'r2', lump_sum: '255000.00', retention_percent: '10' });
    const unit = { ...round, pricing_mode: 'unit_price' as const, discount_percent: '3' };
    expect(termsFromRound({ ...base, lump_sum: '1' }, unit)).toMatchObject({ lump_sum: null, discount_percent: '3' });
  });

  it('maps a rule id onto its i18n key', () => {
    expect(ruleKey('award.bidder_blocked')).toBe('tendering.award_rule.bidder_blocked');
  });

  it('reads the gate out of an award refusal and ignores other errors', () => {
    const gate = { subcontractor_id: 's', findings: [] };
    const refusal = new ApiError(409, 'Conflict', { detail: { code: 'award.bidder_blocked', message: 'x', gate } });
    expect(gateOfError(refusal)).toEqual({ code: 'award.bidder_blocked', gate });
    expect(gateOfError(new ApiError(409, 'Conflict', { detail: { code: 'other' } }))).toBeNull();
    expect(gateOfError(new Error('x'))).toBeNull();
  });
});

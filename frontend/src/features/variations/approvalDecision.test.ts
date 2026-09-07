// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The approval boundary's own arithmetic (Issue #435). The rendered flow is
// tested in commercialBoundaryPayloads.test.tsx; what is pinned here is the
// part a screen test cannot show clearly: the exact wire keys, and the two
// edges of "does this amount depart from what was submitted".
//
// The keys matter on their own because the approve route accepts unknown ones.
// `decided_amount` is what it reads; `agreed_cost_impact` is what it serves
// back, and posting the figure under that name returns 200 and records the
// bill total instead. Nothing downstream would report the difference.

import { describe, it, expect } from 'vitest';
import {
  approvalBaseline,
  approvalBlockReason,
  buildApprovalPayload,
  departsFromBaseline,
  AGREED_AMOUNT_EPSILON,
} from './approvalDecision';
import type { VariationRequest } from './api';

const REQUEST: VariationRequest = {
  id: 'vr-1',
  project_id: 'p-1',
  notice_id: null,
  code: 'VR-001',
  title: 'Re-measure of the piling to grid F',
  description: '',
  requested_by: null,
  requested_at: null,
  classification: 'scope_change',
  urgency: 'med',
  estimated_cost_impact: '12000.00',
  estimated_schedule_days: 4,
  currency: 'EUR',
  status: 'submitted',
  submitted_at: '2026-08-20T09:00:00Z',
  decision_at: null,
  decision_notes: '',
  decided_by: null,
  submitted_boq_id: 'boq-1',
  submitted_boq_total: '7500.00',
  agreed_cost_impact: null,
  agreed_basis: '',
  agreed_variance_note: '',
  metadata: {},
  created_at: '2026-08-19T09:00:00Z',
  updated_at: '2026-08-20T09:00:00Z',
};

const NO_BILL: VariationRequest = {
  ...REQUEST,
  submitted_boq_id: null,
  submitted_boq_total: null,
};

describe('what an approval is measured against', () => {
  it('measures against the bill that was submitted, not the headline it was raised at', () => {
    expect(approvalBaseline(REQUEST)).toEqual({ amount: 7500, source: 'submitted_boq' });
  });

  it('falls back to the headline when the request carries no bill', () => {
    expect(approvalBaseline(NO_BILL)).toEqual({ amount: 12000, source: 'headline_estimate' });
  });
});

describe('what counts as a departure', () => {
  it('treats an agreed 7,200 against a submitted 7,500 as one', () => {
    expect(departsFromBaseline('7200', approvalBaseline(REQUEST))).toBe(true);
  });

  it('agrees with the server about where the edge is', () => {
    // The service compares with `abs(agreed - baseline) >= _MONEY_EPSILON`,
    // and _MONEY_EPSILON is 0.01. A screen that drew the line anywhere looser
    // would submit an approval the server then refuses with a 422 the approver
    // had no way to anticipate.
    expect(AGREED_AMOUNT_EPSILON).toBe(0.01);
    expect(departsFromBaseline('7500.01', approvalBaseline(REQUEST))).toBe(true);
    expect(departsFromBaseline('7500.005', approvalBaseline(REQUEST))).toBe(false);
    expect(departsFromBaseline('7500', approvalBaseline(REQUEST))).toBe(false);
  });
});

describe('when the approval cannot be sent', () => {
  const base = approvalBaseline(REQUEST);

  it('never blocks approving the pricing state that was submitted', () => {
    expect(
      approvalBlockReason(
        { mode: 'as_submitted', agreedAmount: '', varianceNote: '', decisionNotes: '' },
        base,
      ),
    ).toBeNull();
  });

  it('asks for the amount once the approver says they negotiated one', () => {
    expect(
      approvalBlockReason(
        { mode: 'negotiated', agreedAmount: '  ', varianceNote: '', decisionNotes: '' },
        base,
      ),
    ).toBe('amount_missing');
  });

  it('asks why, and only where the figure departs from what was submitted', () => {
    expect(
      approvalBlockReason(
        { mode: 'negotiated', agreedAmount: '7200', varianceNote: '', decisionNotes: '' },
        base,
      ),
    ).toBe('variance_note_missing');
    expect(
      approvalBlockReason(
        { mode: 'negotiated', agreedAmount: '7500', varianceNote: '', decisionNotes: '' },
        base,
      ),
    ).toBeNull();
  });
});

describe('the body that goes over the wire', () => {
  it('names the amount under the key the route reads', () => {
    expect(
      buildApprovalPayload({
        mode: 'negotiated',
        agreedAmount: ' 7200 ',
        varianceNote: ' Settled after the joint re-measure. ',
        decisionNotes: '',
      }),
    ).toEqual({
      decided_amount: '7200',
      agreed_variance_note: 'Settled after the joint re-measure.',
    });
  });

  it('sends no amount when the submitted pricing state is accepted', () => {
    // The absence is the message: it is what makes the server record a basis
    // of priced_boq or headline_estimate rather than filing the approval as a
    // negotiation that happens to match.
    expect(
      buildApprovalPayload({
        mode: 'as_submitted',
        agreedAmount: '9999',
        varianceNote: 'ignored',
        decisionNotes: 'Fair against the contract rates.',
      }),
    ).toEqual({ decision_notes: 'Fair against the contract rates.' });
  });

  it('emits no key it has nothing to say for', () => {
    const payload = buildApprovalPayload({
      mode: 'negotiated',
      agreedAmount: '7500',
      varianceNote: '',
      decisionNotes: '',
    });
    expect(Object.keys(payload)).toEqual(['decided_amount']);
  });
});

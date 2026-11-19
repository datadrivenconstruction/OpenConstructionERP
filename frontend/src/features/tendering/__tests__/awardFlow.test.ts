// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';

import type { PackageHeader, RejectionsPreview } from '../api';
import { dateOrderWarnings, headerChanges, headerForm, rejectionsToSend } from '../awardFlow';

const header = (over: Partial<PackageHeader> = {}): PackageHeader => ({
  package_id: 'p1',
  legal_entity_id: null,
  trade: 'Drywall',
  cost_line_id: null,
  issue_date: '2026-03-02',
  questions_until: '2026-03-16',
  bids_due: null,
  award_planned: null,
  buyer_id: null,
  estimator_id: null,
  site_manager_id: null,
  approver_id: null,
  issuing_entity: { id: 'e1', code: 'NORD', name: 'Bau GmbH Nord', source: 'project' },
  cost_line: null,
  budget: '430000.00',
  currency: 'EUR',
  active_entity_count: 2,
  warnings: [],
  ...over,
});

describe('package header form', () => {
  it('takes bids due from the old deadline when the header has none', () => {
    expect(headerForm(header(), '2026-03-23T12:00:00Z').bids_due).toBe('2026-03-23');
    expect(headerForm(header({ bids_due: '2026-03-30' }), '2026-03-23').bids_due).toBe('2026-03-30');
  });

  it('sends only what changed, blanks as null', () => {
    const before = headerForm(header());
    const after = { ...before, trade: '  ', bids_due: '2026-03-23' };
    expect(headerChanges(before, after)).toEqual({ trade: null, bids_due: '2026-03-23' });
  });

  it('flags dates that run backwards and skips empty ones', () => {
    const form = { ...headerForm(header()), questions_until: '2026-03-25', bids_due: '2026-03-23' };
    expect(dateOrderWarnings(form)).toEqual(['questions_until_after_bids_due']);
    expect(dateOrderWarnings(headerForm(header()))).toEqual([]);
  });
});

describe('rejections to send', () => {
  const preview = (awarded: boolean): RejectionsPreview => ({
    package_id: 'p1',
    awarded,
    issuing_entity: null,
    pending: 0,
    rows: [
      { bid_id: 'b2', company_name: 'Ausbau Sued', email: 'a@x.de', notified_at: null, state: 'pending', last_error: null },
      { bid_id: 'b3', company_name: 'Innenausbau Ost', email: '', notified_at: null, state: 'no_email', last_error: null },
      { bid_id: 'b4', company_name: 'Bau Mitte', email: 'm@x.de', notified_at: '2026-04-01', state: 'sent', last_error: null },
      { bid_id: 'b5', company_name: 'Putz Nord', email: 'p@x.de', notified_at: null, state: 'failed', last_error: 'smtp' },
    ],
  });

  it('counts pending and failed letters once the package is awarded', () => {
    expect(rejectionsToSend(preview(true))).toBe(2);
    expect(rejectionsToSend(preview(false))).toBe(0);
    expect(rejectionsToSend(undefined)).toBe(0);
  });
});

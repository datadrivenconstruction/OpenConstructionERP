// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The invite used to drop the picked subcontractor's id, so the bidder, and
// the contract an award drafts from it, named nobody the directory knows.

import { describe, it, expect } from 'vitest';

import { bidderPayload, linkStillHolds } from './inviteBidder';

const picked = { id: 'sub-1', name: 'Rheinbeton GmbH' };

describe('bidderPayload', () => {
  it('carries the directory id of a picked subcontractor', () => {
    expect(bidderPayload('pkg-1', 'Rheinbeton GmbH', 'bids@rb.test', picked)).toEqual({
      package_id: 'pkg-1',
      company_name: 'Rheinbeton GmbH',
      contact_email: 'bids@rb.test',
      subcontractor_id: 'sub-1',
    });
  });

  it('drops the link once the company is edited to another firm', () => {
    expect(bidderPayload('pkg-1', 'Kranbau AG', 'x@k.test', picked).subcontractor_id).toBeNull();
    expect(linkStillHolds(picked, '  Rheinbeton GmbH ')).toBe(picked);
  });

  it('sends no link for a bidder typed by hand', () => {
    const payload = bidderPayload('pkg-1', '', 'bids@acme.test', null);
    expect(payload.subcontractor_id).toBeNull();
    expect(payload.company_name).toBe('bids@acme.test');
  });
});

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { tallyInvitations } from '../BidLinkCell';
import type { BidInvitation } from '../bidInvitations';

const link = (recipient_id: string, status: BidInvitation['status']): BidInvitation => ({
  id: `${recipient_id}-${status}`,
  package_id: 'p',
  recipient_id,
  company_name: recipient_id,
  email: '',
  status,
  expires_at: '',
  opened_at: null,
  draft_saved_at: null,
  submitted_at: null,
  revoked_at: null,
  bid_id: null,
  created_at: '',
});

describe('tallyInvitations', () => {
  it('counts each recipient once by its newest link', () => {
    // The API lists newest first; an older revoked link must not count again.
    const items = [link('a', 'submitted'), link('a', 'revoked'), link('b', 'opened')];
    const tally = tallyInvitations(items, ['a', 'b', 'c']);
    expect(tally).toEqual({ no_link: 1, not_opened: 0, opened: 1, submitted: 1, expired: 0, revoked: 0 });
  });
});

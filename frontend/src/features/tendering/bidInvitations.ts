// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Staff API for bidder price-entry links (authenticated).
 *
 * Backed by /api/v1/tendering/packages/{id}/bid-invitations/ and
 * /recipients/{rid}/bid-link/. The token itself is returned once, inside
 * `url`, by `createBidLink`; listings never carry it.
 */

import { apiGet, apiPost } from '@/shared/lib/api';

export type BidInvitationStatus = 'not_opened' | 'opened' | 'submitted' | 'expired' | 'revoked';

export interface BidInvitation {
  id: string;
  package_id: string;
  recipient_id: string;
  company_name: string;
  email: string;
  status: BidInvitationStatus;
  expires_at: string;
  opened_at: string | null;
  draft_saved_at: string | null;
  submitted_at: string | null;
  revoked_at: string | null;
  bid_id: string | null;
  created_at: string;
}

export interface BidInvitationCreated extends BidInvitation {
  url: string;
  replaced_count: number;
}

export function listBidInvitations(packageId: string): Promise<{ items: BidInvitation[]; total: number }> {
  return apiGet(`/v1/tendering/packages/${packageId}/bid-invitations/`);
}

/**
 * Make a new link. A firm that already submitted gets a read-only receipt
 * link unless `reopen` is set, which lets it revise and submit again.
 */
export function createBidLink(
  packageId: string,
  recipientId: string,
  options: { reopen?: boolean } = {},
): Promise<BidInvitationCreated> {
  const query = options.reopen ? '?reopen=true' : '';
  return apiPost<BidInvitationCreated>(
    `/v1/tendering/packages/${packageId}/recipients/${encodeURIComponent(recipientId)}/bid-link/${query}`,
    {},
  );
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The bidder an invite creates, and whether it stays tied to the directory.
 *
 * An award makes the bidder's directory entry the counterparty of the contract
 * it drafts, so a bidder picked from the Subcontractor Directory has to carry
 * that entry's id. A bidder typed by hand carries none and the contract falls
 * back to the company name.
 *
 * The link lasts only while the company field still reads what the picker put
 * there. Editing it means the user is inviting some other firm, and keeping the
 * old id would bind the contract to the firm they moved away from.
 */

import type { CreateBidderPayload } from './api';

export interface PickedSubcontractor {
  id: string;
  name: string;
}

/** The picked entry, or null once the company text no longer names it. */
export function linkStillHolds(
  picked: PickedSubcontractor | null,
  company: string,
): PickedSubcontractor | null {
  if (!picked) return null;
  return company.trim() === picked.name.trim() ? picked : null;
}

export function bidderPayload(
  packageId: string,
  company: string,
  email: string,
  picked: PickedSubcontractor | null,
): CreateBidderPayload {
  const link = linkStillHolds(picked, company);
  return {
    package_id: packageId,
    company_name: company.trim() || email.trim(),
    contact_email: email.trim(),
    subcontractor_id: link ? link.id : null,
  };
}

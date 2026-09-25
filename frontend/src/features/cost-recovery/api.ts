// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Back-charges raised from the record the cost came from.
 *
 * The recovery ledger itself lives on the change-intelligence page; this is
 * the narrow write a punch item or an NCR needs to hand its cost to the party
 * responsible, plus the read of what a subcontractor still owes back.
 */
import { apiGet, apiPost } from '@/shared/lib/api';

const CR_BASE = '/v1/cost-recovery';

export type BackChargeSourceKind = 'punch_item' | 'ncr';

export interface BackChargeSource {
  kind: BackChargeSourceKind;
  id: string;
}

/** The create body a source-linked back-charge sends. */
export interface SourceBackChargeBody {
  punch_item_id?: string;
  ncr_id?: string;
  subcontractor_id?: string;
  responsible_party?: string;
}

/** Only the link and the party go out: the backend reads gross, currency and
 *  description off the source record, so nothing typed twice can disagree. */
export function sourceBackChargeBody(
  source: BackChargeSource,
  subcontractorId: string,
  party: string,
): SourceBackChargeBody {
  const body: SourceBackChargeBody =
    source.kind === 'punch_item' ? { punch_item_id: source.id } : { ncr_id: source.id };
  if (subcontractorId) body.subcontractor_id = subcontractorId;
  const label = party.trim();
  if (label) body.responsible_party = label;
  return body;
}

export interface CreatedBackCharge {
  id: string;
  gross_amount: string;
  currency: string;
  responsible_party: string;
}

export function createSourceBackCharge(
  projectId: string,
  body: SourceBackChargeBody,
): Promise<CreatedBackCharge> {
  return apiPost<CreatedBackCharge, SourceBackChargeBody>(
    `${CR_BASE}/projects/${projectId}/back-charges`,
    body,
  );
}

export interface PendingBackCharges {
  subcontractor_id: string;
  items: {
    back_charge_id: string;
    project_id: string;
    source_ref: string;
    description: string;
    currency: string;
    amount: string;
    apportioned: boolean;
  }[];
  /** Per currency, never summed across currencies. */
  totals: Record<string, string>;
}

export function getPendingBackCharges(projectId: string, subcontractorId: string): Promise<PendingBackCharges> {
  return apiGet<PendingBackCharges>(
    `${CR_BASE}/projects/${projectId}/pending-backcharges?subcontractor_id=${encodeURIComponent(subcontractorId)}`,
  );
}

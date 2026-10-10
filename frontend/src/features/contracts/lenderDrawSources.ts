// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { apiGet } from '@/shared/lib/api';
import { getClaimSubRollup } from '@/features/subcontractors/api';
import { getPaymentApplication, listContractDocuments } from './api';
import {
  composeLenderPreparation,
  type ClaimWaiverReference,
  type LenderPreparationContext,
  type PreparationSource,
} from './lenderDrawPreview';

function source<T>(result: PromiseSettledResult<T>): PreparationSource<T> {
  return result.status === 'fulfilled'
    ? { status: 'available', data: result.value }
    : { status: 'unavailable' };
}

/** All source requests are existing authenticated reads. Never follows document URLs. */
export async function loadLenderPreparation(context: LenderPreparationContext) {
  const [application, rollup, documents, waivers] = await Promise.allSettled([
    getPaymentApplication(context.claimId),
    getClaimSubRollup(context.claimId),
    listContractDocuments(context.contractId),
    apiGet<ClaimWaiverReference[]>(
      `/v1/contracts/progress-claims/${encodeURIComponent(context.claimId)}/lien-waivers`,
    ),
  ]);
  if (application.status === 'rejected') throw application.reason;
  return composeLenderPreparation(context, application.value, {
    subcontractors: source(rollup),
    documents: source(documents),
    waivers: source(waivers),
  }, new Date().toISOString());
}

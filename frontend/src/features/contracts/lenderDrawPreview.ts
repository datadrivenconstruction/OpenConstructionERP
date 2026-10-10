// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { ContractDocument, PaymentApplication } from './api';
import type { ClaimSubRollup } from '@/features/subcontractors/api';

export interface LenderPreparationContext {
  claimId: string;
  contractId: string;
  projectId: string;
}

/** References already registered on the claim, not newly issued legal documents. */
export interface ClaimWaiverReference {
  waiver_type: string;
  through_date: string;
  amount: string;
  signed_by: string;
  jurisdiction: string;
  document_url: string;
  notes: string;
  attached_at: string;
  attached_by: string | null;
}

export type PreparationSource<T> =
  | { status: 'available'; data: T }
  | { status: 'unavailable' };

export interface LenderPreparation {
  kind: 'draft_lender_preparation';
  read_at: string;
  application: PaymentApplication;
  subcontractors: PreparationSource<ClaimSubRollup>;
  contract_documents: PreparationSource<ContractDocument[]>;
  claim_waivers: PreparationSource<ClaimWaiverReference[]>;
  /** Deliberately never asserts readiness for lender approval or disbursement. */
  not_included: readonly [
    'loan_facility',
    'lender_approval',
    'stored_material_evidence',
    'contract_change_order_log',
  ];
}

/** No arithmetic or inferred period: the canonical response is copied verbatim. */
export function composeLenderPreparation(
  context: LenderPreparationContext,
  application: PaymentApplication,
  sources: {
    subcontractors: PreparationSource<ClaimSubRollup>;
    documents: PreparationSource<ContractDocument[]>;
    waivers: PreparationSource<ClaimWaiverReference[]>;
  },
  readAt: string,
): LenderPreparation {
  if (
    application.claim_id !== context.claimId ||
    application.contract_id !== context.contractId ||
    application.project_id !== context.projectId
  ) throw new Error('Payment application context mismatch');

  const rollup = sources.subcontractors;
  const subcontractors: PreparationSource<ClaimSubRollup> =
    rollup.status === 'available' && (
      rollup.data.claim_id !== context.claimId ||
      rollup.data.contract_id !== context.contractId ||
      rollup.data.project_id !== context.projectId ||
      rollup.data.currency !== application.currency
    ) ? { status: 'unavailable' } : rollup;
  const documents = sources.documents;
  const contractDocuments: PreparationSource<ContractDocument[]> =
    documents.status === 'available' && documents.data.some(
      (document) => document.contract_id !== context.contractId,
    ) ? { status: 'unavailable' } : documents;

  return structuredClone({
    kind: 'draft_lender_preparation',
    read_at: readAt,
    application,
    subcontractors,
    contract_documents: contractDocuments,
    claim_waivers: sources.waivers,
    not_included: [
      'loan_facility', 'lender_approval', 'stored_material_evidence', 'contract_change_order_log',
    ],
  } satisfies LenderPreparation);
}

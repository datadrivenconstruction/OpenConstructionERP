// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { describe, expect, it } from 'vitest';
import type { ClaimSubRollup } from '@/features/subcontractors/api';
import type { ContractDocument, PaymentApplication } from './api';
import { composeLenderPreparation } from './lenderDrawPreview';

const context = { claimId: 'claim-1', contractId: 'contract-1', projectId: 'project-1' };
const unavailable = { status: 'unavailable' } as const;

function application(currency: string, amount: string): PaymentApplication {
  return {
    claim_id: context.claimId, contract_id: context.contractId, project_id: context.projectId,
    application_number: '2', period_start: '2026-02-01', period_end: '2026-02-28',
    claim_date: '2026-03-01', currency, claim_status: 'draft', retainage_percent: '5',
    summary: {
      original_contract_sum: amount, change_orders_net: '-1', contract_sum_to_date: amount,
      total_completed_stored: amount, retainage: '0', total_earned_less_retainage: amount,
      previous_certificates_total: '7', previous_certificates_basis: 'reconstructed',
      current_payment_due: amount, balance_to_finish: '0',
    },
    lines: [], certification: { certified_amount: null },
  };
}

describe('draft lender preparation composition', () => {
  it.each([['JPY', '9007199254740993'], ['EUR', '123.40'], ['KWD', '123.457']])(
    'preserves canonical %s decimal strings and period without recalculation', (currency, amount) => {
      const source = application(currency, amount);
      const before = structuredClone(source);
      const draft = composeLenderPreparation(context, source, {
        subcontractors: unavailable, documents: unavailable, waivers: unavailable,
      }, '2026-10-07T12:00:00Z');
      expect(draft.application).toEqual(before);
      expect(draft.application.summary.current_payment_due).toBe(amount);
      expect(draft.application.summary.previous_certificates_total).toBe('7');
      expect(draft.application.certification.certified_amount).toBeNull();
      expect(draft.application.summary.previous_certificates_basis).toBe('reconstructed');
      expect(source).toEqual(before);
      source.summary.current_payment_due = '999';
      expect(draft.application.summary.current_payment_due).toBe(amount);
      expect(draft.kind).toBe('draft_lender_preparation');
      expect(draft.not_included).toEqual([
        'loan_facility', 'lender_approval', 'stored_material_evidence', 'contract_change_order_log',
      ]);
    },
  );

  it.each(['claim_id', 'contract_id', 'project_id'] as const)('rejects a stale or foreign %s', (field) => {
    expect(() => composeLenderPreparation(context, { ...application('EUR', '5.00'), [field]: 'other' }, {
      subcontractors: unavailable, documents: unavailable, waivers: unavailable,
    }, 'now')).toThrow('context mismatch');
  });

  it('retains missing periods and optional failures instead of inferring dates or completeness', () => {
    const source = { ...application('EUR', '5.00'), period_start: null, period_end: null };
    const draft = composeLenderPreparation(context, source, {
      subcontractors: unavailable, documents: unavailable, waivers: unavailable,
    }, 'now');
    expect(draft.application.period_start).toBeNull();
    expect(draft.application.period_end).toBeNull();
    expect(draft.subcontractors.status).toBe('unavailable');
    expect(draft.contract_documents.status).toBe('unavailable');
    expect(draft.claim_waivers.status).toBe('unavailable');
  });

  it('preserves explicit-only matching, skipped currencies and waiver evidence from the rollup', () => {
    const rollup = {
      claim_id: context.claimId, contract_id: context.contractId, project_id: context.projectId,
      currency: 'EUR', period_matching: 'explicit_only', as_of: null, skipped_foreign_currency: 2,
      included: [{ id: 'pay-app', lien_waiver_received: false }],
    } as unknown as ClaimSubRollup;
    const draft = composeLenderPreparation(context, application('EUR', '5.00'), {
      subcontractors: { status: 'available', data: rollup }, documents: unavailable, waivers: unavailable,
    }, 'now');
    expect(draft.subcontractors).toEqual({ status: 'available', data: rollup });
    expect(composeLenderPreparation(context, application('USD', '5.00'), {
      subcontractors: { status: 'available', data: rollup }, documents: unavailable, waivers: unavailable,
    }, 'now').subcontractors).toEqual(unavailable);
  });

  it.each(['claim_id', 'contract_id', 'project_id'] as const)('omits a rollup with mismatched %s', (field) => {
    const rollup = {
      claim_id: context.claimId, contract_id: context.contractId, project_id: context.projectId,
      currency: 'EUR', [field]: 'other',
    } as ClaimSubRollup;
    const draft = composeLenderPreparation(context, application('EUR', '5.00'), {
      subcontractors: { status: 'available', data: rollup }, documents: unavailable, waivers: unavailable,
    }, 'now');
    expect(draft.subcontractors).toEqual(unavailable);
  });

  it('omits a document source containing a foreign contract reference', () => {
    const documents = [
      { id: 'own-document', contract_id: context.contractId },
      { id: 'foreign-document', contract_id: 'other-contract' },
    ] as ContractDocument[];
    const draft = composeLenderPreparation(context, application('EUR', '5.00'), {
      subcontractors: unavailable, documents: { status: 'available', data: documents }, waivers: unavailable,
    }, 'now');
    expect(draft.contract_documents).toEqual(unavailable);
    expect(JSON.stringify(draft)).not.toContain('foreign-document');
  });
});

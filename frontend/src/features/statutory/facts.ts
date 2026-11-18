// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ClaimantRole, OwnerSector, StatutoryFacts } from './api';

export interface StatutoryForm {
  role: ClaimantRole;
  sector: OwnerSector;
  events: Record<string, string>;
  contractValue: string;
  paymentAmount: string;
  retentionAmount: string;
}

const blank = (v: string): string | null => (v.trim() === '' ? null : v.trim());

/** The request body for one jurisdiction; empty inputs are left out, not sent as zero. */
export function buildStatutoryFacts(jurisdiction: string, form: StatutoryForm): StatutoryFacts {
  const events = Object.fromEntries(Object.entries(form.events).filter(([, d]) => d));
  const payment = blank(form.paymentAmount);
  const held = blank(form.retentionAmount);
  return {
    jurisdiction,
    sector: form.sector,
    contract_value: blank(form.contractValue),
    notices: { role: form.role, events },
    retention: payment && held ? { payment_amount: payment, retention_amount: held } : null,
  };
}

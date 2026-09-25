/**
 * Prefill for a payment application raised from a contract progress claim.
 *
 * The backend fills the same figures when the form leaves them empty, so this
 * only shows the person what will be sent and lets them change it first. The
 * claim's gross and retention are the period figures, so the net the form
 * implies (gross less retention) is the claim's own net due unless the claim
 * also pays back released retention.
 */
import type { ProgressClaimOption } from './api';

export interface PayappDraft {
  period: string;
  number: string;
  gross: string;
  retention: string;
}

export function payappDraftFromClaim(claim: ProgressClaimOption, fallbackPeriod: string): PayappDraft {
  return {
    period: claim.period || fallbackPeriod,
    number: claim.claim_number || '',
    gross: claim.gross_amount || '',
    retention: claim.retention_amount || '',
  };
}

/** Picker label: contract code, claim number and period, whichever are known. */
export function progressClaimLabel(claim: ProgressClaimOption): string {
  return [claim.contract_code, claim.claim_number, claim.period].filter(Boolean).join(' · ');
}

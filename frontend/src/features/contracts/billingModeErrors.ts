// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A contract is billed either by its payment plan or by measured progress,
// never both. The server refuses the other mode with a 409 whose detail names
// the reason; this turns those codes into words in the reader's language. Any
// other error answers null so the caller keeps its own message.

import type { TFunction } from 'i18next';
import { ApiError } from '@/shared/lib/api';

/** The `detail.error` code of a refused request, if the server sent one. */
export function apiErrorCode(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: { error?: unknown } } | null;
  const code = body?.detail && typeof body.detail === 'object' ? body.detail.error : null;
  return typeof code === 'string' ? code : null;
}

/** A translated sentence for a billing-mode refusal, or null for any other error. */
export function billingModeErrorMessage(t: TFunction, err: unknown): string | null {
  switch (apiErrorCode(err)) {
    case 'contract_billed_by_payment_plan':
      return t('contracts.billed_by_payment_plan', {
        defaultValue:
          'This contract is billed by its payment plan. Claim the next instalment instead of measured progress, so the same work is not billed twice.',
      });
    case 'instalment_claim_not_rebuilt':
      return t('contracts.instalment_claim_not_rebuilt', {
        defaultValue:
          'This claim bills a payment-plan instalment for its agreed amount, so it is not rebuilt from progress.',
      });
    default:
      return null;
  }
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The cached reads of one progress claim, and what a write to its lines makes
// stale.
//
// A claim's stored gross, retention and net are derived from its lines, and so
// are its G702 face, its submission check and its row in the register. A
// screen that writes a line and keeps any of those is showing figures from
// before the write - which is how a claim gets billed on totals nobody
// recognises. So the write path names them in one place rather than each
// caller remembering the list.

import type { QueryClient } from '@tanstack/react-query';

/** The claim itself. Also the prefix of its line-level reads, so it is invalidated with them. */
export function claimKey(claimId: string) {
  return ['contracts', 'claim', claimId] as const;
}

export function claimLinesKey(claimId: string) {
  return ['contracts', 'claim-lines', claimId] as const;
}

/** The G702 / G703 application, which is drawn from the same lines. */
export function aiaApplicationKey(claimId: string) {
  return ['contracts', 'aia-application', claimId] as const;
}

/** Nest under the claim so every existing claim refresh also updates these figures. */
export function paymentApplicationKey(claimId: string) {
  return [...claimKey(claimId), 'payment-application'] as const;
}

/** Every claims list, whichever contract it is filtered to. */
export const CLAIMS_LIST_KEY = ['contracts', 'claims'] as const;

/**
 * Drop everything a claim's lines feed, after a write to them.
 *
 * `claimKey` is a prefix, so the claim's own reads that hang under it (the
 * submission check) go with it.
 */
export function invalidateClaimAfterLineWrite(qc: QueryClient, claimId: string): void {
  qc.invalidateQueries({ queryKey: claimKey(claimId) });
  qc.invalidateQueries({ queryKey: claimLinesKey(claimId) });
  qc.invalidateQueries({ queryKey: aiaApplicationKey(claimId) });
  qc.invalidateQueries({ queryKey: CLAIMS_LIST_KEY });
}

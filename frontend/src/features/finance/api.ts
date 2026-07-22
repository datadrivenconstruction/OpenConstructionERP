// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Finance module.
 *
 * Backed by /api/v1/finance/ - see backend/app/modules/finance/router.py and
 * schemas.py. The shapes here mirror the Pydantic response models exactly so
 * the page can drop straight onto the API.
 */

import { apiGet } from '@/shared/lib/api';

/* ── Retention / withholding ledger ───────────────────────────────────── */

/**
 * One retainage rollup line: either a per-counterparty group or a
 * per-(currency, direction) total.
 *
 * Money fields (scheduled / held_to_date / released_to_date / outstanding) are
 * Decimal-as-string. The ``*_pct`` fields are 0-100 percentages as strings, or
 * null when the denominator (held or scheduled retention) is zero - render
 * "n/a" in that case rather than a bogus 0%.
 *
 * Mirrors backend RetentionRollupResponse.
 */
export interface RetentionRollup {
  currency_code: string;
  direction: string; // "payable" | "receivable"
  contact_id: string | null;
  counterparty_name: string | null;
  scheduled: string;
  held_to_date: string;
  released_to_date: string;
  outstanding: string;
  payment_count: number;
  released_pct: string | null;
  outstanding_pct: string | null;
  held_vs_scheduled_pct: string | null;
  earliest_release_date: string | null;
  latest_release_date: string | null;
}

/**
 * Project retention / withholding ledger.
 *
 * ``groups`` are per-counterparty lines (each within one currency and
 * direction); ``totals`` roll them up per (currency, direction). ``as_of`` is
 * the release-date cutoff used to classify retainage as released.
 *
 * Mirrors backend RetentionLedgerResponse.
 */
export interface RetentionLedger {
  project_id: string;
  as_of: string | null;
  groups: RetentionRollup[];
  totals: RetentionRollup[];
}

/**
 * Fetch the project retention / withholding ledger: per-counterparty groups
 * and per-(currency, direction) totals of retention scheduled, held, released
 * and still outstanding. ``asOf`` is the release-date cutoff (defaults to
 * today server-side). Requires the ``finance.read`` permission.
 */
export function getRetentionLedger(
  projectId: string,
  asOf?: string,
): Promise<RetentionLedger> {
  const qs = new URLSearchParams();
  qs.set('project_id', projectId);
  if (asOf) qs.set('as_of', asOf);
  return apiGet<RetentionLedger>(`/v1/finance/retention-ledger/?${qs.toString()}`);
}

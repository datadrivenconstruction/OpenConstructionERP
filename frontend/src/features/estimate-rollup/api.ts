// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the estimate rollup.
 *
 * The backend composes a project's full estimate headline number out of three
 * figures tracked in separate modules that never roll up on their own: the BOQ
 * base (measured works), the preliminaries total, and the remaining allowances /
 * contingency. This read-only view lets a card render
 *
 *     estimate_total = BOQ base + preliminaries + allowances
 *
 * with the component lines that always sum exactly to the total. Every money
 * amount is a Decimal-as-string on the wire; the card only ever formats it for
 * display, never does arithmetic on it.
 */

import { apiGet } from '@/shared/lib/api';

/** One component line of the composition (keys are stable, labels are English). */
export interface RollupLine {
  /** Stable machine key: boq_base | preliminaries | allowances | contingency. */
  key: string;
  /** English default label (localised in the UI off {@link key}). */
  label: string;
  /** The line's contribution, Decimal-as-string. */
  amount: string;
}

export interface PreliminariesBreakdown {
  total: string;
  fixed_total: string;
  time_related_total: string;
  item_count: number;
}

export interface AllowancesBreakdown {
  total: string;
  provisional_sum_total: string;
  pc_sum_total: string;
  contingency_total: string;
  allowance_count: number;
  /** Foreign currencies with no FX rate to the base (summed in own units). */
  unconverted_currencies: string[];
}

export interface EstimateRollup {
  project_id: string;
  /** Currency every amount is expressed in ('' when the project has none set). */
  base_currency: string;
  boq_base: string;
  preliminaries: PreliminariesBreakdown;
  allowances: AllowancesBreakdown;
  estimate_total: string;
  lines: RollupLine[];
}

/** Fetch a project's composed estimate rollup (BOQ base + prelims + allowances). */
export async function fetchEstimateRollup(projectId: string): Promise<EstimateRollup> {
  return apiGet<EstimateRollup>(`/v1/estimate-rollup/projects/${projectId}`);
}

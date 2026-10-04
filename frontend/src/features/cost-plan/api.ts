// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API client for the NRM 1 elemental cost plan.
 *
 * The backend regroups one bill into the NRM 1 structure and reads the bill's
 * own markup cascade below it. Every money figure is a decimal string on the
 * wire; this feature only formats them and never adds them up, because the
 * server already guarantees that the rows sum to the bill's direct cost and
 * grand total.
 */

import { API_BASE, activeLanguageTag, apiGet, downloadWithAuth } from '@/shared/lib/api';

/** Money and ratios share one shape on every row. */
export interface CostPlanSubtotal {
  total: string;
  /** Total divided by GIFA, or null when no GIFA is known. */
  cost_per_m2: string | null;
  /** Share of the cost plan total in percent, or null when the total is zero. */
  share_pct: string | null;
}

export interface CostPlanElement extends CostPlanSubtotal {
  code: string;
  /** Element title from the NRM 1 table (data, not an interface string). */
  name: string;
  position_count: number;
}

export interface CostPlanGroupLevel extends CostPlanSubtotal {
  position_count: number;
  /** The distinct codes that landed on the group without an element. */
  codes: string[];
}

export interface CostPlanGroup extends CostPlanSubtotal {
  code: string;
  name: string;
  kind: 'works' | 'addon';
  position_count: number;
  elements: CostPlanElement[];
  group_level: CostPlanGroupLevel | null;
}

export type PlacementReason =
  | 'matched'
  | 'group_level'
  | 'unknown_element'
  | 'no_code'
  | 'invalid_code'
  | 'unknown_group';

export interface CostPlanUnallocatedPosition {
  id: string;
  ordinal: string;
  description: string;
  code: string | null;
  reason: PlacementReason;
  total: string;
}

export interface CostPlanUnallocated extends CostPlanSubtotal {
  position_count: number;
  positions: CostPlanUnallocatedPosition[];
  positions_truncated: boolean;
}

export interface CostPlanMarkup extends CostPlanSubtotal {
  id: string | null;
  /** The estimator's own name for the line. */
  name: string;
  category: string;
  markup_type: string;
  apply_to: string;
  percentage: string | null;
  fixed_amount: string | null;
  /** What the line was computed on; null for a lump sum or a scoped stack. */
  base: string | null;
  running_total: string;
  scoped: boolean;
}

export type CostPlanWarning =
  | 'unallocated_positions'
  | 'no_gifa'
  | 'addons_in_bill_and_markups'
  | 'scoped_markups';

export interface Nrm1CostPlan {
  standard: 'NRM1';
  boq_id: string;
  boq_name: string;
  project_id: string;
  currency: string;
  gifa: string | null;
  gifa_source: 'project' | 'entered' | 'none';
  groups: CostPlanGroup[];
  /** NRM 1 group 0 alone. */
  facilitating_works_estimate: CostPlanSubtotal;
  /** NRM 1 groups 1-8 alone, the figure cost per m2 GIFA is benchmarked on. */
  building_works_estimate: CostPlanSubtotal;
  addon_groups: CostPlanGroup[];
  unallocated: CostPlanUnallocated;
  direct_cost: CostPlanSubtotal;
  markups: CostPlanMarkup[];
  markups_total: CostPlanSubtotal;
  grand_total: CostPlanSubtotal;
  /** Real positions only; an empty "Add Position" row is not counted. */
  position_count: number;
  /** Positions placed on a group, by element or at group level. */
  allocated_count: number;
  inherited_count: number;
  warnings: string[];
}

function query(gifa: string | null | undefined, extra?: Record<string, string>): string {
  const params = new URLSearchParams();
  if (gifa) params.set('gifa', gifa);
  for (const [key, value] of Object.entries(extra ?? {})) params.set(key, value);
  const text = params.toString();
  return text ? `?${text}` : '';
}

export const costPlanApi = {
  /** The bill rolled up into NRM 1. `gifa` overrides the project's area for this reading. */
  nrm1(boqId: string, gifa?: string | null): Promise<Nrm1CostPlan> {
    return apiGet<Nrm1CostPlan>(`/v1/cost-plan/boqs/${boqId}/nrm1${query(gifa)}`);
  },

  /** Download the same plan as an Excel workbook in the reader's language. */
  exportNrm1Xlsx(boqId: string, gifa?: string | null): Promise<void> {
    const lang = activeLanguageTag();
    return downloadWithAuth(
      `${API_BASE}/v1/cost-plan/boqs/${boqId}/nrm1/export.xlsx${query(gifa, lang ? { locale: lang } : undefined)}`,
      'NRM1 cost plan.xlsx',
    );
  },
};

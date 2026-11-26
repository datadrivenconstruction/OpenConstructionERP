// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { apiGet } from '@/shared/lib/api';

/** Money arrives as Decimal-encoded strings; never sum them as floats. */
export interface CostTypeGridTotals {
  budget: string;
  committed: string;
  actual: string;
  forecast: string;
  eac: string;
  variance: string;
}

export type EacBasis = 'forecast' | 'committed' | 'actual';

export interface CostTypeGridRow extends CostTypeGridTotals {
  line_id: string;
  cost_code: string;
  cost_code_title: string;
  /** A stored budget category, or null when it is outside the vocabulary. */
  cost_type: string | null;
  category: string;
  description: string;
  currency: string;
  eac_basis: EacBasis;
  committed_from_documents: boolean;
  /** 'resources' or 'no_resources' for lines the BOQ split wrote, else null. */
  split_basis: string | null;
  editable: boolean;
}

export interface CostTypeGridGroup {
  cost_code: string;
  cost_code_title: string;
  rows: CostTypeGridRow[];
  subtotal: CostTypeGridTotals;
}

export interface CostTypeGridTypeTotal {
  /** A budget category, or 'untyped'. */
  cost_type: string;
  line_count: number;
  totals: CostTypeGridTotals;
}

export interface CostTypeGridFinding {
  rule_id: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
  suggestion: string;
  element_ref: string | null;
}

export interface CostTypeGrid {
  project_id: string;
  currency: string;
  /** The cost types in display order. */
  cost_types: string[];
  groups: CostTypeGridGroup[];
  by_type: CostTypeGridTypeTotal[];
  total: CostTypeGridTotals;
  line_count: number;
  findings: CostTypeGridFinding[];
}

export const costTypeGridKey = (projectId: string) => ['costmodel', 'cost-type-grid', projectId] as const;

export function fetchCostTypeGrid(projectId: string): Promise<CostTypeGrid> {
  return apiGet<CostTypeGrid>(`/v1/costmodel/projects/${projectId}/5d/cost-type-grid/`);
}

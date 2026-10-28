// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cross-tab navigation contract for the Cost Explorer. A result row in one tab
// can hand a work item or a rate code to another tab (compare it across bases,
// or test a substitution) without the user re-entering anything.

export type CostExplorerTab = 'by-resources' | 'find-work' | 'compare' | 'substitute';

export interface WorkRef {
  cost_item_id: string;
  code: string;
  description?: string;
  unit?: string;
  region?: string | null;
  currency?: string;
}

export interface SubstituteSeed extends WorkRef {
  /** Pre-selected resource line to re-price, when known. */
  resource_code?: string;
  resource_name?: string;
  /** Resources already known to be in this work (from a by-resources match). */
  candidates?: Array<{ code: string; name: string }>;
}

export interface CrossNav {
  openCompare: (code: string) => void;
  openSubstitute: (seed: SubstituteSeed) => void;
}

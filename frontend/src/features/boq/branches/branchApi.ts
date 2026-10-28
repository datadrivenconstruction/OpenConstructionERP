// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API client for estimate branches (variants) of a BOQ.
 *
 * A branch is an ordinary bill opened in the same editor; these calls add the
 * tree, the compare, the cherry-pick and the merge on top of it. Money arrives
 * as decimal strings and stays that way until it is formatted.
 */
import { apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';
import { documentExportUrl, type DocumentFormat } from '@/shared/lib/documentExport';
import type { BOQ } from '../api';


export type BranchStatus = 'open' | 'merged' | 'archived';
export type Resolution = 'source' | 'target';
export type CompareView = 'positions' | 'sections' | 'cost_groups';

export interface DesignOptionRef {
  id: string;
  name: string;
  set_id: string | null;
  set_name: string;
  boq_id: string | null;
}

export interface BranchNode {
  boq_id: string;
  name: string;
  is_main: boolean;
  parent_boq_id: string | null;
  status: BranchStatus;
  note: string;
  is_locked: boolean;
  created_at: string | null;
  created_by: string | null;
  author: string;
  position_count: number;
  direct_cost: string;
  grand_total: string;
  delta_vs_parent: string | null;
  base_snapshot_id: string | null;
  source_snapshot_id: string | null;
  merged_at: string | null;
  merged_by: string | null;
  merge_snapshot_id: string | null;
  design_option: DesignOptionRef | null;
}

export interface BranchTree {
  main_boq_id: string;
  currency: string;
  can_merge: boolean;
  nodes: BranchNode[];
  design_options: DesignOptionRef[];
}

export type BranchChangeType = 'added' | 'removed' | 'changed' | 'unchanged';

export interface BranchCompareRow {
  key: string;
  change_type: BranchChangeType;
  changed_fields: string[];
  ordinal: string;
  description: string;
  unit: string;
  a_description: string | null;
  b_description: string | null;
  a_quantity: string | null;
  b_quantity: string | null;
  a_unit_rate: string | null;
  b_unit_rate: string | null;
  a_total: string;
  b_total: string;
  delta: string;
  section_key: string;
  section: string;
  cost_group: string;
}

export interface BranchCompareGroup {
  key: string;
  label: string;
  total_a: string;
  total_b: string;
  delta: string;
}

export interface BranchCompare {
  a_boq_id: string;
  b_boq_id: string;
  a_name: string;
  b_name: string;
  currency: string;
  summary: {
    added: number;
    removed: number;
    changed: number;
    unchanged: number;
    total_a: string;
    total_b: string;
    delta: string;
    delta_percent: number;
  };
  rows: BranchCompareRow[];
  by_section: BranchCompareGroup[];
  by_cost_group: BranchCompareGroup[];
}

export interface PlanFieldValues {
  base: unknown;
  source: unknown;
  target: unknown;
}

export interface PlanItem {
  key: string;
  action: 'add' | 'update' | 'remove';
  conflict: boolean;
  ordinal: string;
  description: string;
  is_section: boolean;
  parent_key: string | null;
  depth: number;
  fields: Record<string, PlanFieldValues>;
}

export interface ApplyPlan {
  source_boq_id: string;
  target_boq_id: string;
  base_known: boolean;
  items: PlanItem[];
  conflicts: number;
}

export interface ApplyResult {
  target_boq_id: string;
  snapshot_id: string | null;
  added: number;
  updated: number;
  removed: number;
  kept_target: number;
  skipped: string[];
  status: string | null;
}

export interface CreateBranchBody {
  name: string;
  note?: string;
  snapshot_id?: string | null;
}

export const branchApi = {
  tree: (boqId: string) => apiGet<BranchTree>(`/v1/boq/boqs/${boqId}/branches/`),

  create: (sourceBoqId: string, body: CreateBranchBody) =>
    apiPost<BOQ, CreateBranchBody>(`/v1/boq/boqs/${sourceBoqId}/branches/`, body),

  update: (branchId: string, body: { name?: string; note?: string; status?: 'open' | 'archived' }) =>
    apiPatch<BranchTree>(`/v1/boq/boqs/${branchId}/branch/`, body),

  compare: (aId: string, bId: string) => apiGet<BranchCompare>(`/v1/boq/boqs/${aId}/branches/compare/${bId}`),

  exportCompare: (aId: string, bId: string, format: DocumentFormat, view: CompareView, locale: string) =>
    downloadWithAuth(
      documentExportUrl(`/v1/boq/boqs/${aId}/branches/compare/${bId}/export`, { format, view, locale }),
      `branch-compare.${format}`,
    ),

  plan: (targetId: string, sourceId: string, keys?: string[]) =>
    apiPost<ApplyPlan>(`/v1/boq/boqs/${targetId}/branches/plan/`, { source_boq_id: sourceId, keys: keys ?? null }),

  cherryPick: (targetId: string, sourceId: string, keys: string[], resolutions: Record<string, Resolution>) =>
    apiPost<ApplyResult>(`/v1/boq/boqs/${targetId}/branches/cherry-pick/`, {
      source_boq_id: sourceId,
      keys,
      resolutions,
    }),

  merge: (branchId: string, resolutions: Record<string, Resolution>, includeMarkups: boolean) =>
    apiPost<ApplyResult>(`/v1/boq/boqs/${branchId}/branch/merge/`, {
      resolutions,
      include_markups: includeMarkups,
      confirm: true,
    }),

  linkDesignOption: (branchId: string, optionId: string | null) =>
    apiPut<BranchTree>(`/v1/boq/boqs/${branchId}/branch/design-option/`, { option_id: optionId }),
};

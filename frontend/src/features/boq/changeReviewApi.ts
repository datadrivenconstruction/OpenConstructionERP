// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Change review API: positions whose drawing got a new revision or whose BIM
 * model got a new version, and the quantity updates a new model version
 * proposes. Quantities and money arrive as strings, exactly as stored.
 */
import { apiGet, apiPost } from '@/shared/lib/api';

export type ChangeFlagSource = 'document_revision' | 'bim_version';
export type ChangeFlagStatus = 'open' | 'reviewed';

export interface ChangeFlag {
  id: string;
  boq_id: string;
  position_id: string;
  ordinal: string;
  description: string;
  source_type: ChangeFlagSource | string;
  source_key: string;
  source_id: string | null;
  source_label: string;
  source_version: string | null;
  /** document_revised | elements_modified | elements_deleted | elements_changed | model_changed */
  reason: string;
  details: Record<string, unknown>;
  detected_via: 'event' | 'scan' | string;
  status: ChangeFlagStatus | string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  created_at: string;
}

export interface ChangeFlagList {
  boq_id: string;
  open_count: number;
  reviewed_count: number;
  flags: ChangeFlag[];
}

export interface ChangeFlagSummary {
  boq_id: string;
  open_count: number;
  open_by_source: Record<string, number>;
}

export interface ChangeFlagScanResult {
  boq_id: string;
  positions_checked: number;
  bim_flags_found: number;
  document_flags_found: number;
  created: number;
  open_count: number;
}

export interface ChangeFlagReviewResult {
  boq_id: string;
  updated: number;
  open_count: number;
}

export type BIMProposalStatus = 'changed' | 'elements_missing' | 'no_quantity';

export interface BIMQuantityProposal {
  position_id: string;
  ordinal: string;
  description: string;
  unit: string;
  unit_rate: string;
  current_quantity: string;
  previous_model_quantity: string;
  new_model_quantity: string;
  delta: string;
  current_total: string;
  new_total: string;
  total_delta: string;
  method: 'unit' | 'rule';
  status: BIMProposalStatus | string;
  appliable: boolean;
  /** The stored quantity differs from what the old model version measured. */
  manual_override: boolean;
  model_id: string | null;
  new_model_id: string | null;
  model_name: string;
  model_version: string;
  element_count: number;
  modified_count: number;
  missing_count: number;
}

export interface BIMQuantityProposals {
  boq_id: string;
  positions_checked: number;
  appliable_count: number;
  total_delta: string;
  rows: BIMQuantityProposal[];
}

export interface BIMQuantityApplyResult {
  boq_id: string;
  applied: number;
  skipped: number;
  total_delta: string;
  results: Array<{
    position_id: string;
    applied: boolean;
    reason: string;
    old_quantity: string | null;
    new_quantity: string | null;
    old_total: string | null;
    new_total: string | null;
  }>;
}

export const changeReviewKeys = {
  summary: (boqId: string) => ['boq-change-flags', boqId, 'summary'] as const,
  flags: (boqId: string, status: string) => ['boq-change-flags', boqId, 'list', status] as const,
  all: (boqId: string) => ['boq-change-flags', boqId] as const,
  proposals: (boqId: string) => ['boq-bim-quantity-proposals', boqId] as const,
};

export const changeReviewApi = {
  summary: (boqId: string) =>
    apiGet<ChangeFlagSummary>(`/v1/boq/boqs/${boqId}/change-flags/summary/`),

  listFlags: (boqId: string, status: 'open' | 'reviewed' | 'all' = 'all') =>
    apiGet<ChangeFlagList>(`/v1/boq/boqs/${boqId}/change-flags/?status=${status}`),

  /** Work out flags from the data. Writes review flags only, never a figure. */
  scan: (boqId: string) =>
    apiPost<ChangeFlagScanResult>(`/v1/boq/boqs/${boqId}/change-flags/scan/`, {}),

  review: (
    boqId: string,
    body: { flag_ids?: string[]; all_open?: boolean; status?: ChangeFlagStatus; note?: string },
  ) =>
    apiPost<ChangeFlagReviewResult, typeof body>(
      `/v1/boq/boqs/${boqId}/change-flags/review/`,
      body,
    ),

  proposals: (boqId: string) =>
    apiGet<BIMQuantityProposals>(`/v1/boq/boqs/${boqId}/bim-quantity-proposals/`),

  /** Human confirm step: only the named positions are written. */
  applyProposals: (boqId: string, positionIds: string[]) =>
    apiPost<BIMQuantityApplyResult, { position_ids: string[] }>(
      `/v1/boq/boqs/${boqId}/bim-quantity-proposals/apply/`,
      { position_ids: positionIds },
    ),
};

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Position to cost item (save, refresh), the composition check, and the
// replacement of one resource row by a ranked match. The server refuses with a
// status; the UI words each refusal from the status, never from server text.

import { ApiError, apiGet, apiPost, apiPut } from '@/shared/lib/api';

export interface SavedCostItem {
  id: string;
  code: string;
  region: string | null;
  rate: string;
}

export interface CompositionComponent {
  index: number;
  name: string;
  quantity: string;
  unit_rate: string;
  issues: string[];
}

export interface PositionComposition {
  stored_unit_rate: string;
  derived_unit_rate: string;
  delta: string;
  coherent: boolean;
  fx_missing: string[];
  components: CompositionComponent[];
}

export interface MatchCandidate {
  cost_item_id: string;
  code: string;
  description: string;
  unit: string;
  unit_rate: number;
  currency: string;
  score: number;
}

export const positionCostItemApi = {
  save: (positionId: string) =>
    apiPost<SavedCostItem, Record<string, never>>(`/v1/costs/from-boq-position/${positionId}/`, {}),
  refresh: (costItemId: string, positionId: string) =>
    apiPut<SavedCostItem, { position_id: string }>(`/v1/costs/from-boq-position/${costItemId}/`, {
      position_id: positionId,
    }),
  composition: (positionId: string) => apiGet<PositionComposition>(`/v1/boq/positions/${positionId}/composition/`),
  match: (query: string, unit: string) =>
    apiPost<MatchCandidate[], { query: string; unit: string | null; top_k: number; mode: string }>(
      '/v1/costs/match/',
      { query, unit: unit || null, top_k: 5, mode: 'lexical' },
    ),
  replace: (positionId: string, index: number, costItemId: string, score: number) =>
    apiPost<unknown, { cost_item_id: string; score: number }>(
      `/v1/boq/positions/${positionId}/resources/${index}/replace/`,
      { cost_item_id: costItemId, score },
    ),
};

/** i18n key and English fallback for a refusal, chosen from the HTTP status. */
export function refusalText(err: unknown, scope: 'save' | 'refresh' | 'replace'): { key: string; fallback: string } {
  const status = err instanceof ApiError ? err.status : 0;
  if (status === 409 && scope === 'save')
    return {
      key: 'boq.position_cost.err_exists',
      fallback: 'This position is already saved as a cost item. Use "Refresh cost item" to update it.',
    };
  if (status === 409)
    return {
      key: 'boq.position_cost.err_locked',
      fallback: 'The bill is locked or the line changed meanwhile. Reload and try again.',
    };
  if (status === 422)
    return scope === 'replace'
      ? {
          key: 'boq.position_cost.err_candidate',
          fallback: 'This match cannot replace the resource (inactive, has variants, or the row no longer exists).',
        }
      : {
          key: 'boq.position_cost.err_not_savable',
          fallback: 'Sections and lines without a unit or description cannot become cost items.',
        };
  if (status === 404 || status === 403)
    return {
      key: 'boq.position_cost.err_not_found',
      fallback: 'The cost item or position was not found, or you cannot change it.',
    };
  return { key: 'boq.position_cost.err_generic', fallback: 'The action failed. Nothing was changed.' };
}

export function confidencePercent(score: number): number {
  return Math.round(Math.min(Math.max(score, 0), 1) * 100);
}

export const ISSUE_CODES = [
  'missing_name',
  'missing_unit',
  'non_positive_quantity',
  'unpriced',
  'negative_rate',
  'total_mismatch',
] as const;

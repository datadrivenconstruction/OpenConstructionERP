// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Project Catalogue: a project's own rates, copied from
 * the cost database or the resource catalogue, edited per project, with the
 * source each copy came from. Rates are decimal strings in and out.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

const BASE = '/v1/project-catalogue';

export type CatalogueStatus = 'in_sync' | 'overridden' | 'source_changed' | 'source_missing' | 'manual';
export type CatalogueSourceType = 'cost_item' | 'catalog_resource';
export type SyncAction = 'take_source' | 'keep_local';

export interface CatalogueItem {
  id: string;
  project_id: string;
  code: string;
  description: string;
  unit: string;
  item_type: string;
  rate: string;
  currency: string;
  note: string;
  source_type: 'manual' | CatalogueSourceType;
  source_id: string | null;
  source_label: string;
  source_code: string;
  source_rate: string | null;
  source_currency: string;
  source_synced_at: string | null;
  current_source_rate: string | null;
  status: CatalogueStatus;
  deviation_percent: string | null;
  linked_positions: number;
  stale_positions: number;
  created_at: string;
  updated_at: string;
  warnings: { rule_id: string; message: string }[];
}

export interface CatalogueSummary {
  total: number;
  in_sync: number;
  overridden: number;
  source_changed: number;
  source_missing: number;
  manual: number;
  linked_positions: number;
  stale_positions: number;
}

export interface CatalogueList {
  items: CatalogueItem[];
  total: number;
  offset: number;
  limit: number;
  summary: CatalogueSummary;
}

export interface SourceHit {
  source_type: CatalogueSourceType;
  source_id: string;
  code: string;
  description: string;
  unit: string;
  rate: string;
  currency: string;
  label: string;
  already_added: boolean;
}

export interface PositionCandidate {
  id: string;
  boq_id: string;
  boq_name: string;
  ordinal: string;
  description: string;
  unit: string;
  quantity: string;
  unit_rate: string;
  linked_item_id: string | null;
}

export interface Paged<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export interface ApplyResult {
  applied: number;
  skipped: number;
  position_ids: string[];
}

export interface OwnRatePayload {
  code: string;
  description: string;
  unit: string;
  rate: string;
  currency: string;
}

export const listItems = (projectId: string, status = '') =>
  apiGet<CatalogueList>(`${BASE}/projects/${projectId}/items?limit=500&status=${encodeURIComponent(status)}`);

export const createItem = (projectId: string, payload: OwnRatePayload) =>
  apiPost<CatalogueItem>(`${BASE}/projects/${projectId}/items`, payload);

export const importItems = (projectId: string, sourceType: CatalogueSourceType, sourceIds: string[]) =>
  apiPost<{ added: number; skipped: number }>(`${BASE}/projects/${projectId}/items/import`, {
    source_type: sourceType,
    source_ids: sourceIds,
  });

export const syncItems = (projectId: string, action: SyncAction, itemIds?: string[]) =>
  apiPost<{ updated: number; skipped: number }>(`${BASE}/projects/${projectId}/items/sync`, {
    action,
    item_ids: itemIds ?? null,
  });

export const searchSources = (projectId: string, sourceType: CatalogueSourceType, q: string) =>
  apiGet<Paged<SourceHit>>(
    `${BASE}/projects/${projectId}/sources?source_type=${sourceType}&limit=50&q=${encodeURIComponent(q)}`,
  );

export const updateItem = (itemId: string, patch: Partial<OwnRatePayload> & { note?: string }) =>
  apiPatch<CatalogueItem>(`${BASE}/items/${itemId}`, patch);

export const deleteItem = (itemId: string) => apiDelete<void>(`${BASE}/items/${itemId}`);

export const listCandidates = (itemId: string, q: string, sameUnit: boolean) =>
  apiGet<Paged<PositionCandidate>>(
    `${BASE}/items/${itemId}/positions?limit=200&same_unit=${sameUnit}&q=${encodeURIComponent(q)}`,
  );

export const applyItem = (itemId: string, positionIds: string[]) =>
  apiPost<ApplyResult>(`${BASE}/items/${itemId}/apply`, { position_ids: positionIds });

export const pushItem = (itemId: string) => apiPost<ApplyResult>(`${BASE}/items/${itemId}/push`, {});

/* -- Pure helpers (unit-tested) ------------------------------------------ */

/** Badge colour for a status: a decision waiting is a warning, a lost source an error. */
export function statusVariant(status: CatalogueStatus): 'success' | 'blue' | 'warning' | 'error' | 'neutral' {
  switch (status) {
    case 'in_sync':
      return 'success';
    case 'overridden':
      return 'blue';
    case 'source_changed':
      return 'warning';
    case 'source_missing':
      return 'error';
    default:
      return 'neutral';
  }
}

/** True when the estimator has a choice to make about this rate. */
export function needsDecision(item: Pick<CatalogueItem, 'status'>): boolean {
  return item.status === 'source_changed';
}

/** A signed percentage for display ("+12.5 %", "-6.8 %"); empty when there is none or it is zero. */
export function formatDeviation(pct: string | null | undefined): string {
  if (pct == null || pct === '') return '';
  const trimmed = pct.trim();
  if (/^-?0(\.0+)?$/.test(trimmed)) return '';
  return `${trimmed.startsWith('-') ? trimmed : `+${trimmed}`} %`;
}

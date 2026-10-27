// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Client for /api/v1/list-views: saved table layouts per list page. */
import { apiDelete, apiGet, apiPatch, apiPost } from './api';
import type { TableViewState } from './tableEnhancer';

export interface ListViewFinding {
  rule_id: string;
  severity: string;
  message: string;
  suggestion: string | null;
}

export interface ListView {
  id: string;
  scope_key: string;
  name: string;
  state: TableViewState & { query?: Record<string, unknown> };
  is_shared: boolean;
  is_default: boolean;
  is_own: boolean;
  created_at: string;
  updated_at: string;
}

export interface ListViewSaved {
  view: ListView;
  findings: ListViewFinding[];
}

const UUID_SEGMENT = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Page key of a route: ids become :id so one view serves every project. */
export function scopeKeyFor(pathname: string): string {
  const parts = pathname
    .split('/')
    .filter(Boolean)
    .map((p) => (UUID_SEGMENT.test(p) || /^\d+$/.test(p) ? ':id' : p.replace(/[^A-Za-z0-9_.:-]/g, '-')));
  return (parts.join('/') || 'home').slice(0, 200);
}

export const listViewsApi = {
  list: (scopeKey: string) => apiGet<ListView[]>(`/v1/list-views/?scope_key=${encodeURIComponent(scopeKey)}`),
  create: (body: { scope_key: string; name: string; state: TableViewState; is_shared: boolean; is_default?: boolean }) =>
    apiPost<ListViewSaved>('/v1/list-views/', body),
  update: (id: string, body: Partial<Pick<ListView, 'name' | 'state' | 'is_shared' | 'is_default'>>) =>
    apiPatch<ListViewSaved>(`/v1/list-views/${id}`, body),
  remove: (id: string) => apiDelete(`/v1/list-views/${id}`),
};

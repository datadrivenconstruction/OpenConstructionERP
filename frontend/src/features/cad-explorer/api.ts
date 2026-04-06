/**
 * API helpers for CAD Data Explorer.
 * Endpoints prefixed with /v1/takeoff/cad-data/.
 */

import { apiGet, apiPost } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export interface ColumnDescriptor {
  name: string;
  dtype: 'string' | 'number';
  non_null: number;
  unique: number;
  top?: string;
  top_freq?: number;
  min?: number;
  max?: number;
  mean?: number;
  sum?: number;
}

export interface DescribeResponse {
  filename: string;
  format: string;
  total_elements: number;
  total_columns: number;
  columns: ColumnDescriptor[];
}

export interface ValueCountItem {
  value: string;
  count: number;
  percentage: number;
}

export interface ValueCountsResponse {
  column: string;
  total: number;
  values: ValueCountItem[];
}

export interface ElementsResponse {
  total: number;
  offset: number;
  limit: number;
  columns: string[];
  rows: Record<string, unknown>[];
}

export interface AggregateGroup {
  key: Record<string, string>;
  results: Record<string, number>;
  count: number;
}

export interface AggregateResponse {
  groups: AggregateGroup[];
  totals: Record<string, number>;
  total_count: number;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export async function describeSession(sessionId: string): Promise<DescribeResponse> {
  return apiPost<DescribeResponse>('/v1/takeoff/cad-data/describe', { session_id: sessionId });
}

export async function valueCounts(
  sessionId: string,
  column: string,
  limit = 50,
): Promise<ValueCountsResponse> {
  return apiPost<ValueCountsResponse>('/v1/takeoff/cad-data/value-counts', {
    session_id: sessionId,
    column,
    limit,
  });
}

export async function fetchElements(
  sessionId: string,
  params: {
    offset?: number;
    limit?: number;
    sort_by?: string;
    sort_order?: 'asc' | 'desc';
    filter_column?: string;
    filter_value?: string;
  } = {},
): Promise<ElementsResponse> {
  const qs = new URLSearchParams({ session_id: sessionId });
  if (params.offset != null) qs.set('offset', String(params.offset));
  if (params.limit != null) qs.set('limit', String(params.limit));
  if (params.sort_by) qs.set('sort_by', params.sort_by);
  if (params.sort_order) qs.set('sort_order', params.sort_order);
  if (params.filter_column) qs.set('filter_column', params.filter_column);
  if (params.filter_value) qs.set('filter_value', params.filter_value);
  return apiGet<ElementsResponse>(`/v1/takeoff/cad-data/elements?${qs.toString()}`);
}

export async function aggregate(
  sessionId: string,
  groupBy: string[],
  aggregations: Record<string, string>,
): Promise<AggregateResponse> {
  return apiPost<AggregateResponse>('/v1/takeoff/cad-data/aggregate', {
    session_id: sessionId,
    group_by: groupBy,
    aggregations,
  });
}

// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers and React Query hooks for quote capture and levelling.
 *
 * Mounted at `/api/v1/quote-capture`. Amounts are decimal strings with a point
 * and no grouping on the wire; the screen formats them per locale.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  API_BASE,
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  extractErrorMessageFromBody,
  fetchWithAuth,
} from '@/shared/lib/api';

export type ConfirmTarget = 'bid' | 'price_list' | 'po_draft';
export const CONFIRM_TARGETS: ConfirmTarget[] = ['bid', 'price_list', 'po_draft'];
export const LOW_CONFIDENCE = 0.7;

export interface Anchor {
  page?: number;
  bbox?: [number, number, number, number];
  sheet?: string;
  row?: number;
  cell?: string;
  cells?: Record<string, string>;
  line?: number;
}

export interface HeaderField {
  value: string | null;
  confidence: number;
  anchor: Anchor | null;
  machine_value: string | null;
  source: string;
}

export interface MatchSuggestion {
  position_id: string | null;
  ordinal?: string;
  description?: string;
  confidence: number;
  status: 'suggested' | 'confirmed' | 'unmatched' | 'rejected';
  alternatives: { position_id: string; ordinal: string; description: string; confidence: number }[];
}

export interface QuoteLine {
  id: string;
  description: string;
  quantity: string;
  unit: string;
  unit_raw?: string;
  unit_rate: string;
  total: string;
  confidence: number;
  anchor: Anchor | null;
  source: string;
  reviewed: boolean;
  ignored?: boolean;
  match: MatchSuggestion | null;
  machine: Record<string, string | null>;
}

export interface QuoteNote {
  id: string;
  kind: 'exclusion' | 'qualification' | 'escalation' | 'validity' | 'payment' | 'delivery';
  text: string;
  confidence: number;
  anchor: Anchor | null;
  acknowledged: boolean;
}

export interface Finding {
  rule_id: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
  element_ref: string | null;
}

export interface QuoteSummary {
  id: string;
  project_id: string;
  package_id: string | null;
  supplier_name: string;
  status: 'draft' | 'in_review' | 'confirmed' | 'rejected';
  source_kind: string;
  original_filename: string;
  extraction_engine: string;
  currency: string;
  quote_total: string;
  created_at: string;
  line_count: number;
  open_findings: number;
}

export interface Quote extends QuoteSummary {
  boq_id: string | null;
  locale: string;
  page_count: number;
  has_file: boolean;
  header: Record<string, HeaderField>;
  lines: QuoteLine[];
  notes: QuoteNote[];
  document: {
    engine?: string;
    pages?: { page: number; width: number; height: number }[];
    lines?: { text: string; anchor: Anchor }[];
  };
  confirmation: { target?: ConfirmTarget; target_id?: string; audit?: unknown[] };
  tax: {
    basis?: string;
    rate?: string | null;
    rate_source?: string;
    tax_name?: string;
    net?: string | null;
    tax?: string | null;
    gross?: string | null;
  };
  findings: Finding[];
}

export interface LevellingCell {
  quote_id: string;
  status: 'quoted' | 'levelled' | 'gap';
  unit_rate: string;
  quoted_total: string;
  adjusted_total: string;
  plug_source: 'price_list' | 'boq' | 'median_of_quotes' | 'none' | null;
  lowest: boolean;
}

export interface Levelling {
  package_id: string;
  currency: string;
  excluded_off_currency: string[];
  rows: {
    position_id: string;
    ordinal: string;
    description: string;
    unit: string;
    quantity: string;
    boq_rate: string;
    price_list_rate: string | null;
    cells: LevellingCell[];
  }[];
  quotes: {
    quote_id: string;
    supplier: string;
    currency: string;
    quoted_total: string;
    levelled_total: string;
    plug_total: string;
    extras_total: string;
    adjusted_total: string;
    priced_rows: number;
    gap_rows: number;
    extra_lines: number;
    exclusions: number;
    rank: number;
  }[];
}

export interface PackageOption {
  id: string;
  name: string;
}

const BASE = '/v1/quote-capture';

export const listPackages = (projectId: string) =>
  apiGet<PackageOption[]>(`/v1/tendering/packages/?project_id=${projectId}`);
export const listQuotes = (projectId: string, packageId?: string) =>
  apiGet<QuoteSummary[]>(
    `${BASE}/projects/${projectId}/quotes${packageId ? `?package_id=${packageId}` : ''}`,
  );
export const getQuote = (id: string) => apiGet<Quote>(`${BASE}/quotes/${id}`);
export const updateQuote = (id: string, body: unknown) => apiPatch<Quote>(`${BASE}/quotes/${id}`, body);
export const updateLine = (id: string, lineId: string, body: unknown) =>
  apiPatch<Quote>(`${BASE}/quotes/${id}/lines/${lineId}`, body);
export const confirmQuote = (id: string, target: ConfirmTarget, acceptWarnings: boolean) =>
  apiPost<{ target_id: string; target: ConfirmTarget }>(`${BASE}/quotes/${id}/confirm`, {
    target,
    accept_warnings: acceptWarnings,
  });
export const deleteQuote = (id: string) => apiDelete(`${BASE}/quotes/${id}`);
export const getLevelling = (packageId: string) =>
  apiGet<Levelling>(`${BASE}/packages/${packageId}/levelling`);
export const createQuoteFromText = (body: { project_id: string; package_id?: string; text: string }) =>
  apiPost<Quote>(`${BASE}/quotes/text`, body);

export async function uploadQuote(projectId: string, file: File, packageId?: string): Promise<Quote> {
  const body = new FormData();
  body.append('file', file);
  if (packageId) body.append('package_id', packageId);
  const response = await fetchWithAuth(`${API_BASE}${BASE}/projects/${projectId}/quotes/upload`, {
    method: 'POST',
    body,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(extractErrorMessageFromBody(payload) ?? `HTTP ${response.status}`);
  return payload as Quote;
}

export async function fetchPageImage(quoteId: string, page: number): Promise<string> {
  const response = await fetchWithAuth(`${API_BASE}${BASE}/quotes/${quoteId}/pages/${page}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return URL.createObjectURL(await response.blob());
}

const keys = {
  packages: (p: string) => ['quote-capture', 'packages', p] as const,
  list: (p: string, pkg?: string) => ['quote-capture', 'list', p, pkg ?? ''] as const,
  quote: (id: string) => ['quote-capture', 'quote', id] as const,
  levelling: (pkg: string) => ['quote-capture', 'levelling', pkg] as const,
};

export const usePackages = (projectId: string) =>
  useQuery({ queryKey: keys.packages(projectId), queryFn: () => listPackages(projectId), enabled: !!projectId });
export const useQuotes = (projectId: string, packageId?: string) =>
  useQuery({
    queryKey: keys.list(projectId, packageId),
    queryFn: () => listQuotes(projectId, packageId),
    enabled: !!projectId,
  });
export const useQuote = (id: string | null) =>
  useQuery({ queryKey: keys.quote(id ?? ''), queryFn: () => getQuote(id as string), enabled: !!id });
export const useLevelling = (packageId: string | undefined) =>
  useQuery({
    queryKey: keys.levelling(packageId ?? ''),
    queryFn: () => getLevelling(packageId as string),
    enabled: !!packageId,
  });

/** A mutation that puts the returned quote in the cache and refreshes lists and levelling. */
export function useQuoteMutation<TArgs>(fn: (args: TArgs) => Promise<Quote>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (quote) => {
      qc.setQueryData(keys.quote(quote.id), quote);
      void qc.invalidateQueries({ queryKey: ['quote-capture', 'list'] });
      void qc.invalidateQueries({ queryKey: ['quote-capture', 'levelling'] });
    },
  });
}

export function useConfirmQuote(quoteId: string, send: typeof confirmQuote = confirmQuote) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ target, acceptWarnings }: { target: ConfirmTarget; acceptWarnings: boolean }) =>
      send(quoteId, target, acceptWarnings),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['quote-capture'] }),
  });
}

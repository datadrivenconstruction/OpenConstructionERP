// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Bid day API client, mounted at `/api/v1/bid-day`. Money is a decimal string
 * with a point. Every edit answers with the whole recalculated board.
 */
import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { API_BASE, apiDelete, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';

export type RowKind = 'subcontract' | 'material' | 'other';
export type Channel = 'portal' | 'phone' | 'email' | 'other';
export type ExclusionStatus = 'open' | 'plugged' | 'included';

export interface Exclusion {
  id: string;
  text: string;
  status: ExclusionStatus;
  plug_amount: string;
}

export interface BidQuote {
  id: string;
  source: 'submission' | 'tender_bid' | 'late' | 'manual';
  channel: Channel;
  vendor: string;
  amount: string;
  source_amount: string | null;
  currency: string;
  fx_rate: string;
  received_at: string | null;
  note: string;
  exclusions: Exclusion[];
  as_quoted: string;
  adjusted: string;
  open_exclusions: number;
  is_chosen: boolean;
  rev: number;
}

export interface Suggestion {
  quote_id: string;
  vendor: string;
  adjusted: string;
  confidence: number;
  reasons: string[];
  gap_pct: number;
  open_exclusions: number;
  is_chosen: boolean;
}

export interface BidRow {
  id: string;
  bid_package_id: string | null;
  name: string;
  kind: RowKind;
  plug_amount: string;
  chosen_quote_id: string | null;
  value: string;
  delta_vs_plug: string;
  suggestion: Suggestion | null;
  quotes: BidQuote[];
  rev: number;
}

export interface Totals {
  direct: string;
  overhead: string;
  risk: string;
  profit: string;
  markup: string;
  bid_total: string;
  estimate_direct: string;
  estimate_total: string;
  vs_estimate: string;
  last_snapshot_total: string | null;
  delta_vs_snapshot: string | null;
}

export interface BoardEvent {
  id: string;
  created_at: string;
  user_name: string;
  kind: string;
  message: string;
  delta: string;
  total_after: string;
  params: Record<string, unknown>;
}

export interface Finding {
  rule_id: string;
  severity: string;
  message: string;
  element_ref: string | null;
  details: Record<string, unknown>;
}

export interface SnapshotSummary {
  id: string;
  created_at: string;
  submitted_by_name: string;
  currency: string;
  bid_total: string;
  note: string;
  content_sha256: string;
  pushed_at: string | null;
}

export interface Board {
  id: string;
  project_id: string;
  tender_id: string;
  tender_name: string;
  deadline: string | null;
  currency: string;
  status: 'open' | 'frozen';
  version: number;
  markup_rev: number;
  overhead_pct: string;
  risk_pct: string;
  profit_pct: string;
  stale_days: number;
  deviation_pct_limit: string;
  totals: Totals;
  rows: BidRow[];
  events: BoardEvent[];
  findings: Finding[];
  snapshots: SnapshotSummary[];
}

export interface PushPlan {
  applied: boolean;
  lines: {
    row: string;
    position_id: string;
    ordinal: string;
    description: string;
    quantity: string;
    old_total: string;
    new_total: string;
    new_unit_rate: string;
  }[];
  skipped: string[];
}

export interface ExclusionInput {
  id?: string;
  text: string;
  status: ExclusionStatus;
  plug_amount: string;
}

export interface QuoteInput {
  vendor: string;
  amount: string;
  currency?: string;
  channel: Channel;
  received_at?: string;
  note?: string;
  exclusions?: ExclusionInput[];
}

export interface QuotePatch {
  vendor?: string;
  amount?: string;
  currency?: string;
  received_at?: string;
  note?: string;
  exclusions?: ExclusionInput[];
  rev?: number;
}

export interface MarkupPatch {
  overhead_pct?: string;
  risk_pct?: string;
  profit_pct?: string;
  stale_days?: number;
  deviation_pct_limit?: string;
  rev?: number;
}

const B = '/v1/bid-day';

export const boardKey = (tenderId: string) => ['bid-day', 'board', tenderId] as const;

export const openBoard = (tenderId: string) => apiGet<Board>(`${B}/tenders/${tenderId}/board`);
export const getVersion = (boardId: string) =>
  apiGet<{ version: number; status: string }>(`${B}/boards/${boardId}/version`);

export const api = {
  addRow: (boardId: string, body: { name: string; kind: RowKind; plug_amount: string }) =>
    apiPost<Board>(`${B}/boards/${boardId}/rows`, body),
  updateRow: (boardId: string, rowId: string, body: { name?: string; kind?: RowKind; plug_amount?: string; rev?: number }) =>
    apiPatch<Board>(`${B}/boards/${boardId}/rows/${rowId}`, body),
  deleteRow: (boardId: string, rowId: string) => apiDelete<Board>(`${B}/boards/${boardId}/rows/${rowId}`),
  choose: (boardId: string, rowId: string, quoteId: string | null, rev?: number) =>
    apiPut<Board>(`${B}/boards/${boardId}/rows/${rowId}/choice`, { quote_id: quoteId, rev }),
  addQuote: (boardId: string, rowId: string, body: QuoteInput) =>
    apiPost<Board>(`${B}/boards/${boardId}/rows/${rowId}/quotes`, body),
  updateQuote: (boardId: string, quoteId: string, body: QuotePatch) =>
    apiPatch<Board>(`${B}/boards/${boardId}/quotes/${quoteId}`, body),
  deleteQuote: (boardId: string, quoteId: string) => apiDelete<Board>(`${B}/boards/${boardId}/quotes/${quoteId}`),
  setMarkups: (boardId: string, body: MarkupPatch) => apiPatch<Board>(`${B}/boards/${boardId}/markups`, body),
  freeze: (boardId: string, note: string) => apiPost<Board>(`${B}/boards/${boardId}/freeze`, { note }),
  reopen: (boardId: string) => apiPost<Board>(`${B}/boards/${boardId}/reopen`),
  push: (boardId: string, snapshotId: string, dryRun: boolean) =>
    apiPost<PushPlan>(`${B}/boards/${boardId}/snapshots/${snapshotId}/push`, { dry_run: dryRun }),
  exportSnapshot: (boardId: string, snapshotId: string, fmt: 'pdf' | 'xlsx') =>
    downloadWithAuth(
      `${API_BASE}${B}/boards/${boardId}/snapshots/${snapshotId}/export?fmt=${fmt}`,
      `submitted-bid.${fmt}`,
    ),
};

/** The board of one tender, kept fresh by polling its cheap version number. */
export function useBoard(tenderId: string | undefined, pollMs = 5000) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: boardKey(tenderId ?? ''),
    queryFn: () => openBoard(tenderId as string),
    enabled: !!tenderId,
  });
  const boardId = query.data?.id;
  const version = query.data?.version;
  useEffect(() => {
    if (!boardId || !tenderId) return undefined;
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      getVersion(boardId)
        .then((v) => {
          if (version !== undefined && v.version > version) {
            void qc.invalidateQueries({ queryKey: boardKey(tenderId) });
          }
        })
        .catch(() => undefined);
    }, pollMs);
    return () => window.clearInterval(timer);
  }, [boardId, version, tenderId, pollMs, qc]);
  return query;
}

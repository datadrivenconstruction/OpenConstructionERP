// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the bid outcome ledger, backed by /api/v1/win-loss/
 * (backend/app/modules/win_loss/router.py).
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

export type BidOutcomeStatus = 'pending' | 'won' | 'lost' | 'withdrawn' | 'no_decision';
export type LostReason = 'price' | 'scope' | 'schedule' | 'relationship' | 'capacity' | 'other';

export const OUTCOMES: BidOutcomeStatus[] = ['pending', 'won', 'lost', 'withdrawn', 'no_decision'];
export const LOST_REASONS: LostReason[] = [
  'price',
  'scope',
  'schedule',
  'relationship',
  'capacity',
  'other',
];

export interface ValidationFinding {
  rule_id: string;
  severity: string;
  message: string;
  suggestion: string | null;
}

export interface BidOutcome {
  id: string;
  title: string;
  client_name: string;
  trade: string;
  submitted_on: string | null;
  outcome: BidOutcomeStatus;
  currency: string;
  our_price: string;
  winning_price: string | null;
  second_price: string | null;
  competitor_count: number | null;
  lost_reason: LostReason | null;
  notes: string;
  size_band: string;
  left_on_table: string | null;
  left_on_table_pct: string | null;
  gap_to_winner: string | null;
  gap_to_winner_pct: string | null;
  warnings: ValidationFinding[];
}

export interface BidOutcomeInput {
  title: string;
  client_name: string;
  trade: string;
  submitted_on: string | null;
  outcome: BidOutcomeStatus;
  currency: string;
  our_price: string;
  winning_price: string | null;
  second_price: string | null;
  competitor_count: number | null;
  lost_reason: LostReason | null;
  notes: string;
}

export interface GroupStat {
  key: string;
  submitted: number;
  won: number;
  lost: number;
  hit_rate_pct: string | null;
  won_value: string;
}

export interface LedgerSummary {
  currency: string;
  currencies: string[];
  submitted: number;
  won: number;
  lost: number;
  open: number;
  hit_rate_pct: string | null;
  won_value: string;
  left_on_table: string;
  left_on_table_wins: number;
  avg_gap_to_winner_pct: string | null;
  avg_competitors: string | null;
  by_client: GroupStat[];
  by_trade: GroupStat[];
  by_size: GroupStat[];
}


export const winLossApi = {
  list: async () => (await apiGet<{ items: BidOutcome[] }>(`/v1/win-loss/`)).items,
  summary: (currency?: string) =>
    apiGet<LedgerSummary>(`/v1/win-loss/summary${currency !== undefined ? `?currency=${encodeURIComponent(currency)}` : ''}`),
  create: (body: BidOutcomeInput) => apiPost<BidOutcome, BidOutcomeInput>(`/v1/win-loss/`, body),
  update: (id: string, body: Partial<BidOutcomeInput>) =>
    apiPatch<BidOutcome, Partial<BidOutcomeInput>>(`/v1/win-loss/${id}`, body),
  remove: (id: string) => apiDelete(`/v1/win-loss/${id}`),
};

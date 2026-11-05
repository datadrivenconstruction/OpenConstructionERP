// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Bid / no-bid API client, mounted at `/api/v1/bid-no-bid`. Every edit answers with the whole scorecard. */
import { useQuery } from '@tanstack/react-query';
import { apiGet, apiPatch, apiPost, apiPut } from '@/shared/lib/api';
import type { Scores, Weights } from './logic';

export interface Finding {
  rule_id: string;
  severity: string;
  message: string;
  element_ref: string | null;
}

export interface ScorecardEvent {
  id: string;
  user_name: string;
  kind: string;
  message: string;
  created_at: string;
}

export interface Scorecard {
  id: string;
  project_id: string;
  tender_id: string;
  tender_name: string;
  opportunity_id: string | null;
  weights: Weights;
  scores: Scores;
  notes: Partial<Record<string, string>>;
  threshold: number;
  score: string | null;
  recommendation: '' | 'bid' | 'no_bid';
  decision: '' | 'bid' | 'no_bid';
  decision_reason: string;
  decided_by_name: string;
  decided_at: string | null;
  outcome: '' | 'won' | 'lost' | 'withdrawn';
  outcome_note: string;
  version: number;
  findings: Finding[];
  events: ScorecardEvent[];
}

export interface ScorecardPatch {
  weights?: Partial<Weights>;
  scores?: Partial<Scores>;
  notes?: Partial<Record<string, string>>;
  threshold?: number;
  version?: number;
}

export interface LedgerRow {
  id: string;
  tender_id: string;
  tender_name: string;
  score: string | null;
  threshold: number;
  recommendation: string;
  decision: string;
  decision_reason: string;
  decided_at: string | null;
  outcome: string;
  outcome_source: string;
}

export interface Ledger {
  summary: {
    total: number;
    bid: number;
    no_bid: number;
    undecided: number;
    won: number;
    lost: number;
    win_rate_pct: string | null;
  };
  rows: LedgerRow[];
}


export const scorecardKey = (tenderId: string) => ['bid-no-bid', 'scorecard', tenderId] as const;
export const ledgerKey = (projectId: string) => ['bid-no-bid', 'ledger', projectId] as const;

export const api = {
  open: (tenderId: string) => apiGet<Scorecard>(`/v1/bid-no-bid/tenders/${tenderId}/scorecard`),
  update: (id: string, body: ScorecardPatch) => apiPatch<Scorecard>(`/v1/bid-no-bid/scorecards/${id}`, body),
  decide: (id: string, decision: 'bid' | 'no_bid', reason: string, version: number) =>
    apiPost<Scorecard>(`/v1/bid-no-bid/scorecards/${id}/decision`, { decision, reason, version }),
  outcome: (id: string, outcome: string, note: string, version?: number) =>
    apiPut<Scorecard>(`/v1/bid-no-bid/scorecards/${id}/outcome`, { outcome, note, version }),
  ledger: (projectId: string) => apiGet<Ledger>(`/v1/bid-no-bid/ledger?project_id=${projectId}`),
};

export function useScorecard(tenderId: string | undefined) {
  return useQuery({
    queryKey: scorecardKey(tenderId ?? ''),
    queryFn: () => api.open(tenderId as string),
    enabled: !!tenderId,
  });
}

export function useLedger(projectId: string | undefined) {
  return useQuery({
    queryKey: ledgerKey(projectId ?? ''),
    queryFn: () => api.ledger(projectId as string),
    enabled: !!projectId,
  });
}

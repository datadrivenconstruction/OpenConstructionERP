// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Typed client for the basis-of-estimate module (/api/v1/estimate-basis).
//
// The document derives from the finished estimate: which trades are present,
// absent or flagged by the coverage check. Trade rollup totals arrive as
// Decimal-compatible strings (never a float); the UI formats them for display
// and never does arithmetic on them.

import { apiGet, apiPost, apiPut } from '@/shared/lib/api';

export type QualificationCategory = 'inclusion' | 'exclusion' | 'assumption';

export interface QualificationItem {
  id: string;
  category: QualificationCategory;
  text: string;
  trade_code: string | null;
  trade_label: string | null;
  basis: string;
  source: 'auto' | 'manual';
  enabled: boolean;
}

export interface TradePresence {
  code: string;
  label: string;
  core: boolean;
  position_count: number;
  /** Rolled-up total for the trade, as a Decimal string. */
  total: string;
}

export interface TradeRef {
  code: string;
  label: string;
}

export interface CoverageSummary {
  present_trades: TradePresence[];
  absent_trades: TradeRef[];
  total_positions: number;
  classified_positions: number;
  unclassified_positions: number;
  zero_rate_positions: number;
  missing_quantity_positions: number;
  provisional_positions: number;
  by_others_positions: number;
}

/**
 * The money the document qualifies, snapshotted when it was generated.
 *
 * Every amount is a Decimal string, never a number. The two flags come from the
 * BOQ roll-up and mean what they mean there: the total is not safe to read as
 * final.
 */
export interface FinancialsSummary {
  direct_cost: string;
  markups_total: string;
  grand_total: string;
  currency: string;
  is_mixed_currency: boolean;
  has_unresolved_escalation: boolean;
  markup_count: number;
  boq_count: number;
}

/** The four families a `Position.source` value folds into. */
export type ProvenanceFamilyKey = 'measured' | 'imported' | 'catalogue' | 'manual';

export interface ProvenanceBucket {
  source: string;
  family: string;
  position_count: number;
  total: string;
  share_pct: string;
}

export interface ProvenanceFamily {
  family: string;
  position_count: number;
  total: string;
  share_pct: string;
}

/**
 * One piece of evidence behind the suggested class. `code` is an enum key the
 * UI translates and `value` is the number that goes in the sentence, so the
 * reasoning is never English coming off the wire.
 */
export interface ClassReason {
  code: string;
  value: string;
}

/** The class the platform proposes. Never the decision - see `estimate_class`. */
export interface ClassSuggestion {
  suggested_class: number;
  base_class: number;
  reasons: ClassReason[];
}

export interface ProvenanceSummary {
  buckets: ProvenanceBucket[];
  families: ProvenanceFamily[];
  total_positions: number;
  priced_total: string;
  /** What the shares are a share OF: value normally, counts on a bill with no money. */
  share_basis: string;
  ai_position_count: number;
  ai_total: string;
  scored_position_count: number;
  low_confidence_count: number;
  low_confidence_total: string;
  model_linked_positions: number;
  stale_links: number;
  broken_links: number;
  suggestion: ClassSuggestion;
}

/** One AACE 18R-97 class as the platform publishes it. */
export interface EstimateClassOption {
  estimate_class: number;
  label: string;
  accuracy_low: string;
  accuracy_high: string;
  definition_level_low: number;
  definition_level_high: number;
  methodology: string;
}

export interface EstimateClassCatalog {
  items: EstimateClassOption[];
}

export interface EstimateBasisDocument {
  id: string;
  project_id: string;
  boq_id: string | null;
  title: string;
  status: string;
  notes: string;
  inclusions: QualificationItem[];
  exclusions: QualificationItem[];
  assumptions: QualificationItem[];
  coverage: CoverageSummary;
  financials: FinancialsSummary;
  provenance: ProvenanceSummary;
  currency: string;
  pricing_date: string | null;
  /** The class an estimator stated. `null` means nobody has stated one. */
  estimate_class: number | null;
  accuracy_low_pct: string;
  accuracy_high_pct: string;
  /** The band applied to the grand total. Blank while no class is stated. */
  accuracy_low_amount: string;
  accuracy_high_amount: string;
  market_conditions: string;
  contingency_rationale: string;
  /** OC-03: client budget target, separate from the calculated estimate. */
  budget_target: BudgetTarget | null;
  generated_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** OC-03: client's stated budget target alongside the calculated estimate. */
export interface BudgetTarget {
  type: 'client_target' | 'budget' | 'tender' | 'contract' | string;
  amount: string;
  currency: string;
  gross_net: 'gross' | 'net';
  contingency_mode: 'included' | 'additional';
  contingency_amount?: string | null;
  source?: string | null;
  date?: string | null;
  notes?: string | null;
}

export interface EstimateBasisSummary {
  id: string;
  project_id: string;
  boq_id: string | null;
  title: string;
  status: string;
  inclusion_count: number;
  exclusion_count: number;
  assumption_count: number;
  estimate_class: number | null;
  grand_total: string;
  currency: string;
  generated_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface EstimateBasisList {
  project_id: string;
  items: EstimateBasisSummary[];
}

export interface GenerateBasisRequest {
  project_id: string;
  boq_id?: string | null;
  title?: string | null;
  currency?: string;
  base_date?: string | null;
}

export interface UpdateBasisRequest {
  title?: string | null;
  status?: 'draft' | 'final' | null;
  notes?: string | null;
  inclusions?: QualificationItem[] | null;
  exclusions?: QualificationItem[] | null;
  assumptions?: QualificationItem[] | null;
  /** AACE class 1-5. Send 0 to unstate it; omit to leave it alone. */
  estimate_class?: number | null;
  accuracy_low_pct?: string | null;
  accuracy_high_pct?: string | null;
  market_conditions?: string | null;
  contingency_rationale?: string | null;
  /** OC-03: client budget target. */
  budget_target?: BudgetTarget | null;
}

const BASE = '/v1/estimate-basis';

/**
 * The AACE 18R-97 class table and its published accuracy bands.
 *
 * Fetched rather than hardcoded: the numbers belong to a standard, the platform
 * keeps one copy of them, and a second copy in the client would be the one that
 * goes stale.
 */
export function listEstimateClasses(): Promise<EstimateClassCatalog> {
  return apiGet<EstimateClassCatalog>(`${BASE}/classes`);
}

/** Draft and store a fresh basis-of-estimate from the project's estimate. */
export function generateBasis(
  body: GenerateBasisRequest,
  init?: { signal?: AbortSignal },
): Promise<EstimateBasisDocument> {
  return apiPost<EstimateBasisDocument, GenerateBasisRequest>(`${BASE}/generate`, body, init);
}

/** List every basis-of-estimate document drafted for a project, newest first. */
export function listBasis(projectId: string): Promise<EstimateBasisList> {
  return apiGet<EstimateBasisList>(`${BASE}/projects/${encodeURIComponent(projectId)}`);
}

/** Fetch one basis-of-estimate document. */
export function getBasis(documentId: string): Promise<EstimateBasisDocument> {
  return apiGet<EstimateBasisDocument>(`${BASE}/documents/${encodeURIComponent(documentId)}`);
}

/** Persist user edits to a basis-of-estimate document. */
export function updateBasis(
  documentId: string,
  body: UpdateBasisRequest,
): Promise<EstimateBasisDocument> {
  return apiPut<EstimateBasisDocument, UpdateBasisRequest>(
    `${BASE}/documents/${encodeURIComponent(documentId)}`,
    body,
  );
}

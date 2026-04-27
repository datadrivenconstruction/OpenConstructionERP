// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { apiPost } from '@/shared/lib/api';

/* ── CWICR matcher types (T12) ─────────────────────────────────────────── */

/** A single ranked CWICR match returned by the matcher API. */
export interface CwicrMatchResult {
  cost_item_id: string;
  code: string;
  description: string;
  unit: string;
  unit_rate: number;
  currency: string;
  /** 0..1 — higher is a stronger match. */
  score: number;
  /** Channel that produced the score: 'lexical' | 'semantic' | 'hybrid'. */
  source: string;
}

/** Matcher mode — pure-lexical is always available, semantic requires the
 *  backend `[semantic]` extra.  We default to 'lexical' on the frontend so
 *  unconfigured deployments don't surface "fell back to lexical" warnings. */
export type CwicrMatchMode = 'lexical' | 'semantic' | 'hybrid';

export interface CwicrMatchRequest {
  query: string;
  unit?: string;
  lang?: string;
  top_k?: number;
  mode?: CwicrMatchMode;
  region?: string;
}

export interface CwicrMatchFromPositionRequest {
  position_id: string;
  top_k?: number;
  mode?: CwicrMatchMode;
  lang?: string;
  region?: string;
}

/** POST /api/v1/costs/match/ — ranked CWICR matches for a free-form query. */
export async function matchCwicr(
  body: CwicrMatchRequest,
): Promise<CwicrMatchResult[]> {
  return apiPost<CwicrMatchResult[], CwicrMatchRequest>(
    '/v1/costs/match/',
    body,
  );
}

/** POST /api/v1/costs/match-from-position/ — same matcher, resolves the
 *  query from an existing BOQ position.  Returns 404 if the position id
 *  does not exist (the api helper raises). */
export async function matchCwicrFromPosition(
  body: CwicrMatchFromPositionRequest,
): Promise<CwicrMatchResult[]> {
  return apiPost<CwicrMatchResult[], CwicrMatchFromPositionRequest>(
    '/v1/costs/match-from-position/',
    body,
  );
}

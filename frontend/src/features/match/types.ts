// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * TypeScript types mirroring the backend match-service envelope.
 *
 * Keep these in lock-step with `backend/app/core/match_service/envelope.py`
 * and `backend/app/modules/match/router.py`.  Once the OpenAPI generator
 * (npm run api:generate) is wired with a running backend, replace these
 * hand-authored types with the imported ones.
 *
 * Treat every server-supplied field as readonly so the panel doesn't
 * accidentally mutate response data shared across React Query consumers.
 */

export type MatchSource = 'bim' | 'pdf' | 'dwg' | 'photo';
export type ConfidenceBand = 'high' | 'medium' | 'low';

/** Tier names produced by the translation cascade (`backend/app/core/translation`). */
export type TranslationTier =
  | 'lookup_muse'
  | 'lookup_iate'
  | 'cache'
  | 'llm'
  | 'fallback';

export interface TranslationResult {
  readonly translated: string;
  readonly source_lang: string;
  readonly target_lang: string;
  readonly tier_used: TranslationTier;
  readonly confidence: number;
  readonly cost_usd: number | null;
}

/** Source-agnostic envelope built from raw element data on the backend. */
export interface ElementEnvelope {
  readonly source: MatchSource;
  readonly source_lang: string;
  readonly category: string;
  readonly description: string;
  readonly properties: Readonly<Record<string, unknown>>;
  readonly quantities: Readonly<Record<string, number>>;
  readonly unit_hint: string | null;
  readonly classifier_hint: Readonly<Record<string, string>> | null;
}

/** One ranked CWICR position returned to the UI. */
export interface MatchCandidate {
  readonly code: string;
  readonly description: string;
  readonly unit: string;
  readonly unit_rate: number;
  readonly currency: string;
  /** Final score 0..1 after boosts. */
  readonly score: number;
  readonly vector_score: number;
  readonly boosts_applied: Readonly<Record<string, number>>;
  readonly confidence_band: ConfidenceBand;
  readonly region_code: string;
  readonly source: string;
  readonly language: string;
  readonly classification: Readonly<Record<string, string>>;
  /** Set when the LLM reranker fired. */
  readonly reasoning: string | null;
}

/** What we send to `POST /api/v1/match/element`. */
export interface MatchElementRequestBody {
  readonly source: MatchSource;
  readonly project_id: string;
  readonly raw_element_data: Readonly<Record<string, unknown>>;
  readonly top_k?: number;
  readonly use_reranker?: boolean;
}

/** Echoed back inside MatchResponse.request — same shape as backend MatchRequest. */
export interface MatchRequestEcho {
  readonly envelope: ElementEnvelope;
  readonly project_id: string;
  readonly top_k: number;
  readonly use_reranker: boolean;
}

export interface MatchResponse {
  readonly request: MatchRequestEcho;
  readonly candidates: ReadonlyArray<MatchCandidate>;
  readonly translation_used: TranslationResult | null;
  readonly auto_linked: MatchCandidate | null;
  readonly took_ms: number;
  readonly cost_usd: number;
}

/** What we send to `POST /api/v1/match/feedback`. */
export interface MatchFeedbackRequestBody {
  readonly project_id: string;
  readonly element_envelope: ElementEnvelope;
  readonly accepted_candidate?: MatchCandidate | null;
  readonly rejected_candidates: ReadonlyArray<MatchCandidate>;
  readonly user_chose_code?: string | null;
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// AI Estimate Builder server-driven meta: the score-band thresholds, the
// allowed construction stages, and the per-pass match-group cap. Fetched
// once per page with React Query and shared through a context so the
// per-stage cards never hardcode the magic numbers (the contract says the
// UI must drive these from the server). When the endpoint is absent (older
// backend not yet restarted) it degrades to the contract defaults so the
// page keeps working with correct bands.

import { createContext, useContext } from 'react';
import { useQuery } from '@tanstack/react-query';

import { aiEstimatorApi, type EstimatorMeta } from './api';

/** Green/amber cutoffs for a [0,1] score. `high` and above = green,
 *  `low` (inclusive) up to `high` = amber, below `low` = gray. These mirror
 *  the backend confidence bands (high >= 0.78, medium >= 0.62). */
export interface ScoreThresholds {
  high: number;
  low: number;
}

/** Contract fallback used until GET /meta is reachable. */
export const DEFAULT_THRESHOLDS: ScoreThresholds = { high: 0.78, low: 0.62 };
export const DEFAULT_MATCH_GROUP_CAP = 25;

/** Resolved meta the page hands to every stage. Always populated (falls
 *  back to the contract defaults when the endpoint 404s). */
export interface ResolvedMeta {
  thresholds: ScoreThresholds;
  matchGroupCap: number;
  constructionStages: string[];
  /** False when the server endpoint was unavailable and we are on defaults. */
  fromServer: boolean;
}

function resolve(meta: EstimatorMeta | undefined): ResolvedMeta {
  if (!meta) {
    return {
      thresholds: DEFAULT_THRESHOLDS,
      matchGroupCap: DEFAULT_MATCH_GROUP_CAP,
      constructionStages: [],
      fromServer: false,
    };
  }
  const high = Number(meta.score_thresholds?.high);
  const low = Number(meta.score_thresholds?.low);
  return {
    thresholds: {
      high: Number.isFinite(high) ? high : DEFAULT_THRESHOLDS.high,
      low: Number.isFinite(low) ? low : DEFAULT_THRESHOLDS.low,
    },
    matchGroupCap:
      Number.isFinite(Number(meta.match_group_cap)) && Number(meta.match_group_cap) > 0
        ? Number(meta.match_group_cap)
        : DEFAULT_MATCH_GROUP_CAP,
    constructionStages: Array.isArray(meta.construction_stages) ? meta.construction_stages : [],
    fromServer: true,
  };
}

/** Fetch meta once per page. On 404 (backend not restarted yet) we keep the
 *  contract defaults rather than erroring - the page must still work. */
export function useAiEstimatorMeta(): ResolvedMeta {
  const metaQ = useQuery({
    queryKey: ['aiest-meta'],
    queryFn: aiEstimatorApi.getMeta,
    staleTime: 5 * 60_000,
    // A missing endpoint is an expected, graceful state - do not retry-storm.
    retry: false,
  });
  return resolve(metaQ.data);
}

// ── Shared thresholds context so leaf cards never replicate the cutoffs ───

const ScoreThresholdsContext = createContext<ScoreThresholds>(DEFAULT_THRESHOLDS);

export const ScoreThresholdsProvider = ScoreThresholdsContext.Provider;

/** Read the active score-band thresholds (defaults outside a provider). */
export function useScoreThresholds(): ScoreThresholds {
  return useContext(ScoreThresholdsContext);
}

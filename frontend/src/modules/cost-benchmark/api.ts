/**
 * Thin client for the Cost Benchmarks own-portfolio endpoint.
 *
 * The endpoint enriches the page with the tenant's OWN real project
 * distribution (cost-per-m2 derived from BOQ grand total / gross floor
 * area). The static industry table in `data/benchmarks.ts` stays the
 * source of truth for the industry reference ranges and is always
 * available offline, so this client degrades gracefully: any error, or a
 * missing endpoint, resolves to `null` and the page renders industry-only.
 */

import { apiPost } from '@/shared/lib/api';

/** A user's own portfolio distribution of cost-per-m2, all money as strings. */
export interface OwnPortfolio {
  project_count: number;
  min: string;
  p25: string;
  median: string;
  p75: string;
  max: string;
  confidence: 'high' | 'medium' | 'low';
  note: string;
}

export interface BenchmarkResponse {
  currency: string;
  own_portfolio: OwnPortfolio | null;
  percentile_vs_own: number | null;
  explanation: string;
}

export interface BenchmarkRequest {
  /** Optional building type filter, matched against Project.project_type. */
  building_type?: string;
  /** Optional region filter, matched against Project.region. */
  region?: string;
  /** Optional currency to scope the distribution to (never blends). */
  currency?: string;
  /** Optional user value to position against the portfolio (cost per m2). */
  cost_per_m2?: number;
}

/**
 * Fetch the tenant's own portfolio distribution for a benchmark question.
 *
 * Returns `null` on any failure (no auth, endpoint absent, network error)
 * so the caller can fall back to the industry-only view without surfacing
 * an error. A 200 with `own_portfolio === null` is the honest
 * "not enough project data" state and is passed through unchanged.
 */
export async function fetchOwnPortfolio(
  req: BenchmarkRequest,
): Promise<BenchmarkResponse | null> {
  try {
    return await apiPost<BenchmarkResponse, BenchmarkRequest>(
      '/v1/costs/benchmark/',
      req,
    );
  } catch {
    // Progressive enhancement: the endpoint is never required for the page
    // to render. Any error leaves the industry-only path intact.
    return null;
  }
}

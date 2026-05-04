// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * Typed fetch wrappers around the match-service HTTP routes.
 *
 *   POST /api/v1/match/element   → MatchResponse
 *   POST /api/v1/match/feedback  → 204 No Content
 *
 * Uses the project's existing `apiPost` helper which handles auth,
 * Accept-Language, error extraction and JSON serialization.
 */

import { apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import type {
  LoadedDatabase,
  MatchAcceptRequestBody,
  MatchAcceptResponse,
  MatchElementRequestBody,
  MatchFeedbackRequestBody,
  MatchResponse,
} from './types';

/**
 * Run the matcher for one element.  The backend handles envelope
 * extraction, translation, vector search and ranking.
 */
export async function matchElement(
  body: MatchElementRequestBody,
): Promise<MatchResponse> {
  return apiPost<MatchResponse, MatchElementRequestBody>(
    '/v1/match/element',
    body,
  );
}

/**
 * Record the user's accept/reject decision.  Returns void; the backend
 * answers 204 No Content.
 */
export async function submitMatchFeedback(
  body: MatchFeedbackRequestBody,
): Promise<void> {
  await apiPost<void, MatchFeedbackRequestBody>('/v1/match/feedback', body);
}

/**
 * Accept a CWICR match — backend creates / updates a BOQ position with
 * the matched cost item, optionally links it to a BIM element, and
 * writes a feedback audit entry in one transaction.
 */
export async function acceptMatch(
  body: MatchAcceptRequestBody,
): Promise<MatchAcceptResponse> {
  return apiPost<MatchAcceptResponse, MatchAcceptRequestBody>(
    '/v1/match/accept',
    body,
  );
}

/**
 * List CWICR catalogues that are *actually loaded* into the SQL table,
 * with both row and vector counts so the UI can render the three
 * empty-state CTAs (no-catalog / not-vectorised / ready).
 */
export async function listLoadedDatabases(): Promise<LoadedDatabase[]> {
  return apiGet<LoadedDatabase[]>('/v1/costs/loaded-databases/');
}

/**
 * Bind the project's match settings to a specific CWICR catalogue.
 * Pass ``null`` to clear the binding (returns the project to the
 * "no catalog selected" empty state).
 */
export async function setProjectCatalog(
  projectId: string,
  catalogId: string | null,
): Promise<{ cost_database_id: string | null }> {
  return apiPatch<
    { cost_database_id: string | null },
    { cost_database_id: string | null }
  >(`/v1/projects/${projectId}/match-settings`, {
    cost_database_id: catalogId,
  });
}

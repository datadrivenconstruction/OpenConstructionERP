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

import { apiPost } from '@/shared/lib/api';
import type {
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

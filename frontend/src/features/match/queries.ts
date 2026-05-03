// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * React Query hooks for the match service.
 *
 * Both endpoints are user-driven actions, not passive loads, so they
 * are exposed as mutations rather than queries.  The component decides
 * when to fire them (on mount via auto-fetch, or on a "Find matches"
 * button press).
 */

import { useMutation } from '@tanstack/react-query';
import { matchElement, submitMatchFeedback } from './api';
import type {
  MatchElementRequestBody,
  MatchFeedbackRequestBody,
  MatchResponse,
} from './types';

/** Mutation that runs the matcher for one element. */
export function useMatchElement() {
  return useMutation<MatchResponse, Error, MatchElementRequestBody>({
    mutationFn: matchElement,
  });
}

/** Mutation that records a feedback event.  Fire-and-forget on the UI side. */
export function useSubmitMatchFeedback() {
  return useMutation<void, Error, MatchFeedbackRequestBody>({
    mutationFn: submitMatchFeedback,
  });
}

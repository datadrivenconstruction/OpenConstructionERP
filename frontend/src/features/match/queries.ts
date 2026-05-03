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

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { acceptMatch, matchElement, submitMatchFeedback } from './api';
import type {
  MatchAcceptRequestBody,
  MatchAcceptResponse,
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

/**
 * Mutation that accepts a CWICR match and writes the result to a BOQ
 * position. On success we invalidate the dependent query trees so the
 * BOQ editor and BIM linked-BOQ panel pick up the new row immediately.
 *
 * Invalidates:
 *   - ``['boq', boqId]`` and the broader ``['boq']`` namespace
 *   - ``['boq-positions-for-link', boqId]`` (AddToBOQModal share)
 *   - ``['bim-elements']`` so the right panel's element list refetches
 *     (the new boq_link brief is embedded inline)
 *   - ``['bim', 'links', bimElementId]`` for the linked-BOQ panel
 */
export function useAcceptMatch() {
  const qc = useQueryClient();
  return useMutation<MatchAcceptResponse, Error, MatchAcceptRequestBody>({
    mutationFn: acceptMatch,
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: ['boq'] });
      qc.invalidateQueries({ queryKey: ['boq', variables.boq_id] });
      qc.invalidateQueries({
        queryKey: ['boq-positions-for-link', variables.boq_id],
      });
      qc.invalidateQueries({ queryKey: ['bim-elements'] });
      if (variables.bim_element_id) {
        qc.invalidateQueries({
          queryKey: ['bim', 'links', variables.bim_element_id],
        });
      }
    },
  });
}

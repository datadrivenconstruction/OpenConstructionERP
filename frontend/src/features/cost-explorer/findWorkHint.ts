// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pure decision helper for the Find-work guidance area. The backend returns a
// single hint/hint_code pair that is either a construction-aware spelling
// suggestion (rendered as a clickable, dismissable "did you mean" chip) or a
// plain no-result / low-confidence note. Keeping the branching here (free of
// React) makes it unit-testable without a DOM or a network.

import type { FindWorkResponse } from './api';

/** hint_code that marks the hint payload as a spelling suggestion. */
export const DID_YOU_MEAN_CODE = 'cost_explorer.hint.did_you_mean';

export type FindWorkHint =
  | { kind: 'suggestion'; suggestion: string }
  | { kind: 'note'; code: string; message: string };

/**
 * Decide what to render under a Find-work search.
 *
 * A spelling suggestion becomes a `suggestion` chip carrying the corrected
 * query; any other backend hint becomes a plain `note`. Returns null when there
 * is nothing to show, or when the current suggestion has already been dismissed.
 *
 * @param res - The find-work response (or its hint fields); may be missing.
 * @param dismissedSuggestion - The suggestion the user dismissed, if any.
 */
export function selectFindWorkHint(
  res: Pick<FindWorkResponse, 'hint' | 'hint_code'> | undefined | null,
  dismissedSuggestion?: string | null,
): FindWorkHint | null {
  const hint = res?.hint?.trim() ?? '';
  const code = res?.hint_code ?? '';
  if (!hint) return null;
  if (code === DID_YOU_MEAN_CODE) {
    if (dismissedSuggestion && dismissedSuggestion === hint) return null;
    return { kind: 'suggestion', suggestion: hint };
  }
  return { kind: 'note', code, message: hint };
}

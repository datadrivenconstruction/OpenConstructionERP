// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The wizard's cost-catalogue step: what it pre-selects, and when "Auto"
// (let the server bind from the project) is allowed.
//
// "Auto" is a real choice, not the absence of one. The pre-select used to
// re-run whenever the pick was empty, so choosing Auto snapped straight back
// to the recommendation, and a pick there also overrode the project's own
// binding (a custom catalogue, or one people already confirmed matches
// against). It now decides once, and never over a binding.

import { useCallback, useEffect, useRef } from 'react';

import type { MatchReadiness, MatchReadinessCode } from './api';

/** The catalogue to pre-select, or null to leave the step on Auto. */
export function preselectFor(
  readiness: MatchReadiness | undefined,
  loadedRegions: readonly string[],
): string | null {
  if (!readiness) return null;
  // Auto keeps an existing binding; auto-bind decides whether a binding in
  // another language may be switched (only before anything is confirmed).
  if (readiness.bound_catalogue) return null;
  // No language means no basis for a recommendation the user did not make.
  if (!readiness.project_language) return null;
  const rec = readiness.recommended_catalogue?.region ?? null;
  return rec && loadedRegions.includes(rec) ? rec : null;
}

/**
 * Why "Auto" cannot run for this project, or null when it can.
 *
 * Auto binds from the project's language. With no language and no binding
 * it would bind nothing and the run would end with "no catalogue", so the
 * user picks one instead.
 */
export function autoBlockedReason(
  readiness: MatchReadiness | undefined,
): Extract<MatchReadinessCode, 'region_unknown' | 'region_language_unknown'> | null {
  if (!readiness) return null;
  if (readiness.project_language || readiness.bound_catalogue) return null;
  const multi = readiness.warnings.some((w) => w.code === 'region_language_unknown');
  return multi ? 'region_language_unknown' : 'region_unknown';
}

/** The session's catalogue field: "" clears a pick (the server ignores null). */
export function sessionCatalogueValue(catalogueId: string | null): string {
  return catalogueId ?? '';
}

/**
 * Pre-select once, when both the readiness answer and the installed list
 * are in; after that, and after any choice by the user, leave it alone.
 * ``choose`` is what the picker calls.
 */
export function useCataloguePreselect(
  readiness: MatchReadiness | undefined,
  loadedRegions: readonly string[],
  catalogueId: string | null,
  setCatalogueId: (id: string | null) => void,
): { choose: (id: string | null) => void } {
  const decided = useRef(false);

  useEffect(() => {
    if (decided.current || !readiness || loadedRegions.length === 0) return;
    decided.current = true;
    if (catalogueId) return;
    const pick = preselectFor(readiness, loadedRegions);
    if (pick) setCatalogueId(pick);
  }, [readiness, loadedRegions, catalogueId, setCatalogueId]);

  const choose = useCallback(
    (id: string | null) => {
      decided.current = true;
      setCatalogueId(id);
    },
    [setCatalogueId],
  );

  return { choose };
}

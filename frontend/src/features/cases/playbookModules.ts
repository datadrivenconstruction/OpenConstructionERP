// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases <-> module route index.
//
// The project-journey map places every major module on the lifecycle line as a
// chip. This helper answers "which guided cases touch this module?" so the map
// can hang a small "N cases" affordance on a module chip and link into the case
// library. It is READ-ONLY over PLAYBOOKS: it never mutates the case registry,
// it only buckets playbooks by the app routes their steps visit.
//
// A case "touches" a module when one of its steps navigates to that module's
// route. Step routes may carry a `/projects/:projectId` prefix and/or a
// `?query`; both are normalised away with the SAME convention the runner uses
// (`resolveStepRoute` for the project prefix, then the query is dropped) so a
// step route and a journey module route compare as plain, unscoped bases such
// as `/boq` or `/portfolio`.

import { PLAYBOOKS } from './playbooks';
import { resolveStepRoute } from './progress';
import type { Playbook } from './types';

/**
 * Normalise a route to the unscoped, query-less base used for matching.
 *
 * `/projects/:projectId/rfi` -> `/rfi`, `/takeoff?tab=measurements` ->
 * `/takeoff`, `/boq` -> `/boq`. Mirrors `resolveStepRoute(to, null)` (the
 * unscoped runner behaviour) and then strips any query so the base lines up
 * with a journey module route.
 */
export function normalizeCaseRoute(to: string): string {
  const unscoped = resolveStepRoute(to, null);
  return unscoped.split('?')[0] ?? unscoped;
}

/**
 * One module a case visits: the route that identifies it, plus the label pair
 * the step carried. `label` is the English fallback and `labelKey` is what
 * every other language reads, exactly as on the step chip.
 */
export interface CaseModuleRef {
  /** Normalised, unscoped route base (`/boq`). The module's identity here. */
  route: string;
  /** English fallback label, from the first step that visits `route`. */
  label: string;
  /** Optional i18n key for the label, from that same step. */
  labelKey?: string;
}

/**
 * The distinct modules one case walks through, in the order its steps reach
 * them.
 *
 * Identity is the ROUTE, not the label, and that choice is load-bearing.
 * `types.ts` spends thirty lines on why `moduleLabel` and `moduleLabelKey` can
 * disagree and why a half-corrected pair reads in review as the fix working.
 * Deduplicating on the label inherits that: two steps that visit `/files` with
 * the labels "Files" and "Documents" would count as two modules and draw two
 * cells for one place. Two steps that visit different routes under a
 * copy-pasted label would collapse into one. Routes cannot drift that way -
 * they are what the runner navigates to.
 *
 * The label pair still comes from the first step at that route, so a cell says
 * the same word its step chip says, in every language.
 */
export function modulesForPlaybook(pb: Playbook): CaseModuleRef[] {
  const out: CaseModuleRef[] = [];
  const seen = new Set<string>();
  for (const step of pb.steps) {
    const route = normalizeCaseRoute(step.to);
    if (!route || seen.has(route)) continue;
    seen.add(route);
    out.push({ route, label: step.moduleLabel, labelKey: step.moduleLabelKey });
  }
  return out;
}

/** Lazily-built, cached map: normalised route base -> playbooks touching it. */
let indexCache: Map<string, Playbook[]> | null = null;

function buildIndex(): Map<string, Playbook[]> {
  if (indexCache) return indexCache;
  const byRoute = new Map<string, Playbook[]>();
  // PLAYBOOKS is already sorted by curated `order`, so each bucket inherits
  // that order - the first entry is the most prominent case for that module.
  for (const pb of PLAYBOOKS) {
    // A case that visits the same route in several steps still counts once
    // for that route, so a multi-step case never inflates the module count.
    const seen = new Set<string>();
    for (const step of pb.steps) {
      const base = normalizeCaseRoute(step.to);
      if (!base || seen.has(base)) continue;
      seen.add(base);
      const bucket = byRoute.get(base);
      if (bucket) bucket.push(pb);
      else byRoute.set(base, [pb]);
    }
  }
  indexCache = byRoute;
  return byRoute;
}

/**
 * The playbooks that touch `route`, in curated order (empty when none). The
 * argument is normalised the same way as step routes, so a journey module
 * route (`/boq`) or a raw step route both resolve correctly.
 */
export function playbooksForRoute(route: string): Playbook[] {
  const base = normalizeCaseRoute(route);
  return buildIndex().get(base) ?? [];
}

/** How many cases touch each normalised route base. */
export function caseCountByRoute(): Map<string, number> {
  const counts = new Map<string, number>();
  for (const [route, list] of buildIndex()) counts.set(route, list.length);
  return counts;
}

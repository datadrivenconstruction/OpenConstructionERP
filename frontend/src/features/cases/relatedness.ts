// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - relatedness: what to run NEXT and which cases are RELATED.
//
// The catalogue is one connected journey, not a set of islands. Each case can
// point at a successor (its outputs feed the next case's first step) and a few
// siblings that touch the same work. A case may author these explicitly
// (`next` / `related` on the Playbook); when it does not, they are derived from
// the metadata every case already carries - discipline, lifecycle stage, the
// modules its steps use, the company types it serves and, above all, the
// in -> out chaining between one case's outputs and another's first-step inputs.
// A deterministic fallback (same discipline, nearest higher order, then the
// next case in the global lifecycle numbering) guarantees no case is a dead end.
//
// Pure and framework-free (same shape as progress.ts) so it is trivially
// testable and carries no React or i18n dependency.

import type { Playbook } from './types';
import { getPlaybook } from './playbooks';
import { stageForPlaybook, STAGE_ORDER, buildCaseNumbers } from './stages';

/** The module ids a case touches, taken from its step routes (stable) rather
 *  than the free-text module labels. `/projects/:projectId/boq` -> `boq`. */
function moduleKeysOf(pb: Playbook): Set<string> {
  const keys = new Set<string>();
  for (const step of pb.steps) {
    const route = step.to.replace(/^\/projects\/:projectId/, '').replace(/\?.*$/, '');
    const seg = route.split('/').find((s) => s.length > 0);
    keys.add(seg ?? 'home');
  }
  return keys;
}

/** Loosely normalize a flow label for matching: lowercase, strip anything that
 *  is not a letter or digit, drop a trailing plural `s`. Turns "Purchase order"
 *  and "purchase orders" into the same stem. A ranking heuristic, not exact. */
function norm(label: string): string {
  const s = label.toLowerCase().replace(/[^a-z0-9]+/g, '');
  return s.endsWith('s') ? s.slice(0, -1) : s;
}

function firstInputs(pb: Playbook): Set<string> {
  const first = pb.steps[0];
  return new Set((first?.inputs ?? []).map((i) => norm(i.label)));
}

function allOutputs(pb: Playbook): Set<string> {
  const out = new Set<string>();
  for (const step of pb.steps) {
    for (const o of step.outputs ?? []) out.add(norm(o.label));
  }
  return out;
}

function overlap(a: Set<string>, b: Set<string>): number {
  let n = 0;
  for (const x of a) if (b.has(x)) n += 1;
  return n;
}

function stageIdx(pb: Playbook): number {
  return STAGE_ORDER[stageForPlaybook(pb)] ?? 0;
}

function resolveIds(ids: string[] | undefined, exclude: Set<string>): Playbook[] {
  const out: Playbook[] = [];
  for (const id of ids ?? []) {
    const pb = getPlaybook(id);
    if (pb && !exclude.has(pb.id)) out.push(pb);
  }
  return out;
}

/**
 * The case(s) to run NEXT after `pb`. Explicit `pb.next` wins; otherwise the
 * successor is derived from output -> input chaining (a case whose first step
 * consumes what this case produces), preferring one further along the
 * lifecycle; failing that the next case in the same discipline, then the next
 * case in the global lifecycle numbering, so there is always somewhere to go.
 */
export function nextCasesFor(pb: Playbook, all: Playbook[], limit = 2): Playbook[] {
  const explicit = resolveIds(pb.next, new Set([pb.id]));
  if (explicit.length) return explicit.slice(0, limit);

  const myOut = allOutputs(pb);
  const myStage = stageIdx(pb);
  const scored = all
    .filter((c) => c.id !== pb.id)
    .map((c) => ({
      c,
      score: overlap(firstInputs(c), myOut),
      forward: stageIdx(c) >= myStage,
    }))
    .filter((r) => r.score > 0)
    .sort(
      (a, b) =>
        b.score - a.score ||
        Number(b.forward) - Number(a.forward) ||
        Math.abs(a.c.order - pb.order) - Math.abs(b.c.order - pb.order),
    );
  if (scored.length) return scored.slice(0, limit).map((r) => r.c);

  const sameCat = all
    .filter((c) => c.category === pb.category && c.order > pb.order)
    .sort((a, b) => a.order - b.order);
  const firstCat = sameCat[0];
  if (firstCat) return [firstCat];

  // Last resort: the next case in the global lifecycle numbering.
  const numbers = buildCaseNumbers(all);
  const mine = numbers.get(pb.id);
  if (mine !== undefined) {
    const following = all.find((c) => numbers.get(c.id) === mine + 1);
    if (following) return [following];
  }
  return [];
}

/**
 * Cases RELATED to `pb`: siblings that touch the same work but are not the
 * linear next step. Explicit `pb.related` comes first; the rest are scored on
 * shared discipline, stage, modules, company types and any in <-> out chaining.
 * Pass `exclude` (usually the `next` ids) so a case never shows in both lists.
 */
export function relatedCasesFor(
  pb: Playbook,
  all: Playbook[],
  exclude: Set<string> = new Set(),
  limit = 4,
): Playbook[] {
  const explicit = resolveIds(pb.related, new Set([pb.id, ...exclude]));

  const myModules = moduleKeysOf(pb);
  const myCompanies = new Set(pb.companyTypes);
  const myOut = allOutputs(pb);
  const myIn = firstInputs(pb);
  const myStage = stageForPlaybook(pb);
  const seen = new Set<string>([pb.id, ...exclude, ...explicit.map((p) => p.id)]);

  const scored = all
    .filter((c) => c.id !== pb.id && !seen.has(c.id))
    .map((c) => {
      const chain =
        overlap(firstInputs(c), myOut) > 0 || overlap(myIn, allOutputs(c)) > 0 ? 1 : 0;
      const score =
        3 * (c.category === pb.category ? 1 : 0) +
        2 * (stageForPlaybook(c) === myStage ? 1 : 0) +
        2 * overlap(moduleKeysOf(c), myModules) +
        1 * overlap(new Set(c.companyTypes), myCompanies) +
        chain;
      return { c, score };
    })
    .filter((r) => r.score >= 4)
    .sort(
      (a, b) => b.score - a.score || Math.abs(a.c.order - pb.order) - Math.abs(b.c.order - pb.order),
    );

  return [...explicit, ...scored.map((r) => r.c)].slice(0, limit);
}

/**
 * The compact "Other cases" strip at the foot of the detail page: the rest of
 * the catalogue beyond next/related, so no case is more than one click from
 * any other. Cases written for the SAME market as `pb` come first (a reader
 * inside the German workflow is most likely to want the other German cases),
 * then the remainder; both groups keep the stable lifecycle numbering the
 * catalogue itself is ordered by. Pass `exclude` (the next/related ids already
 * shown above the strip) so nothing appears on the page twice.
 */
export function moreCasesFor(
  pb: Playbook,
  all: Playbook[],
  exclude: Set<string> = new Set(),
  limit = 12,
): Playbook[] {
  const seen = new Set<string>([pb.id, ...exclude]);
  const pool = all.filter((c) => !seen.has(c.id));
  const numbers = buildCaseNumbers(all);
  const byNumber = (a: Playbook, b: Playbook) =>
    (numbers.get(a.id) ?? Number.MAX_SAFE_INTEGER) -
    (numbers.get(b.id) ?? Number.MAX_SAFE_INTEGER);
  const sameMarket = pb.region
    ? pool.filter((c) => c.region === pb.region).sort(byNumber)
    : [];
  const sameIds = new Set(sameMarket.map((c) => c.id));
  const rest = pool.filter((c) => !sameIds.has(c.id)).sort(byNumber);
  return [...sameMarket, ...rest].slice(0, limit);
}

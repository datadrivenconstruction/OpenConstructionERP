// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - the catalogue of screens a step can open.
//
// Typing a route by hand is the fastest way to author a case that goes
// nowhere, so the editor offers a list instead. The list is not maintained
// here: it is derived from the shipped playbooks, which between them already
// name every screen a case has ever needed, each with the label that case
// gave it. That has two consequences worth stating.
//
// It cannot drift from the app. A route only appears here because a shipped
// case already walks it, so it is a screen that exists and works.
//
// It is not exhaustive, and must not pretend to be. A screen no shipped case
// visits is missing from the list, which is why the editor also accepts a
// typed path. `isKnownTarget` exists so the editor can say "not one of ours"
// as information rather than as a refusal.

import { PLAYBOOKS } from './playbooks';
import { compareNames } from '@/shared/lib/collator';

export interface StepTarget {
  /** The in-app path, e.g. `/boq`. */
  to: string;
  /** The label the shipped cases give this screen, e.g. "Bill of Quantities". */
  label: string;
  /** Translation key for the label when the shipped cases carried one. */
  labelKey?: string;
  /** How many shipped cases step through it. Drives the sort: the screens the
   *  product leans on most are the ones an author is most likely to want. */
  uses: number;
}

/** Strip a query string so `/reports?tab=cost` and `/reports` are one screen
 *  in the picker. The author can still add the query back by hand. */
function basePath(to: string): string {
  return to.split('?')[0] ?? to;
}

function buildCatalogue(): StepTarget[] {
  const byPath = new Map<string, StepTarget>();
  for (const playbook of PLAYBOOKS) {
    for (const step of playbook.steps) {
      const to = basePath(step.to || '');
      if (!to.startsWith('/')) continue;
      const existing = byPath.get(to);
      if (existing) {
        existing.uses += 1;
        // Keep the first label seen. Cases disagree about what to call a
        // screen; picking the first keeps the list stable across builds
        // rather than depending on glob order breaking a tie.
        continue;
      }
      byPath.set(to, {
        to,
        label: step.moduleLabel || to,
        labelKey: step.moduleLabelKey,
        uses: 1,
      });
    }
  }
  return [...byPath.values()].sort(
    (a, b) => b.uses - a.uses || compareNames(a.label, b.label),
  );
}

/** Every screen the shipped cases step through, most-used first. */
export const STEP_TARGETS: StepTarget[] = buildCatalogue();

const KNOWN = new Set(STEP_TARGETS.map((target) => target.to));

/** Whether a path is one the shipped cases already use. */
export function isKnownTarget(to: string): boolean {
  return KNOWN.has(basePath(to || ''));
}

/** The catalogue entry for a path, ignoring any query string. */
export function findTarget(to: string): StepTarget | undefined {
  const path = basePath(to || '');
  return STEP_TARGETS.find((target) => target.to === path);
}

// The same guard the backend applies in `app/modules/cases/schemas.py`. Kept
// in both places on purpose: the backend one is the one that protects the
// data, this one exists so the editor can say no before a round trip rather
// than after. A step target becomes a link, so `javascript:` and the
// protocol-relative `//host/x` both have to be refused - the second is the
// one a "must start with a slash" check waves straight through.
// The colon is allowed for route parameters: the shipped cases step through
// `/projects/:projectId/files` and the runner substitutes the active project.
// It is safe here because the leading slash is mandatory, so a scheme like
// `javascript:` cannot match this pattern at all.
const ROUTE_RE = /^\/(?!\/)[A-Za-z0-9\-_/.:]*(\?[A-Za-z0-9\-_=&%.,:+]*)?$/;

/** Whether a typed path is an acceptable step target. */
export function isValidTarget(to: string): boolean {
  const value = (to || '').trim();
  if (!ROUTE_RE.test(value)) return false;
  return !basePath(value).split('/').includes('..');
}

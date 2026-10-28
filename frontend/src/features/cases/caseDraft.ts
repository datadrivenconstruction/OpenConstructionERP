// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cases - the pure half of the case editor.
//
// Everything here is a pure function over a draft. The editor component owns
// the state and the network; this file owns what a draft is and what the
// operations on one mean, so the rules can be tested without rendering
// anything. Same split as ./progress, which does the equivalent job for a run.
//
// The local-copy check deserves a note. The backend runs the real validation
// and its answer is the one that decides whether a case may be shared. This
// file re-implements the two ERROR rules only, so the editor can grey out the
// share button while you type instead of letting you press it and get a 422
// back. It is a hint, never the authority: if the two ever disagree, the
// backend wins by construction, because it is the one holding the door.

import type { CaseCategory, CompanyType, Playbook, PlaybookStep, ProfessionalRole } from './types';
import { isValidTarget } from './stepTargets';

/** One step while it is being written. Plain text, no translation keys: the
 *  author writes in their own language and nobody translates it afterwards. */
export interface DraftStep {
  id: string;
  title: string;
  what: string;
  why: string;
  moduleLabel: string;
  to: string;
  inputs: string[];
  outputs: string[];
}

/** A case while it is being written. */
export interface CaseDraft {
  title: string;
  description: string;
  longDescription: string;
  category: CaseCategory;
  companyTypes: CompanyType[];
  roles: ProfessionalRole[];
  estMinutes: number;
  sourcePlaybookId: string;
  isShared: boolean;
  steps: DraftStep[];
}

/** Step ids only have to be unique inside one case, and they are what run
 *  progress is keyed by, so they must be stable once written. Sequential is
 *  therefore wrong: deleting step 2 and adding another would reuse `s2` and
 *  inherit the deleted step's completion. A counter that only ever goes up
 *  avoids that without needing a UUID. */
export function nextStepId(steps: readonly DraftStep[]): string {
  let highest = 0;
  for (const step of steps) {
    const match = /^s(\d+)$/.exec(step.id);
    if (match) highest = Math.max(highest, Number(match[1]));
  }
  return `s${highest + 1}`;
}

export function emptyStep(steps: readonly DraftStep[]): DraftStep {
  return {
    id: nextStepId(steps),
    title: '',
    what: '',
    why: '',
    moduleLabel: '',
    to: '',
    inputs: [],
    outputs: [],
  };
}

export function emptyDraft(): CaseDraft {
  return {
    title: '',
    description: '',
    longDescription: '',
    category: 'estimating',
    companyTypes: [],
    roles: [],
    estMinutes: 10,
    sourcePlaybookId: '',
    isShared: false,
    steps: [],
  };
}

/** Move a step one place up or down. Out-of-range moves are no-ops rather
 *  than errors, so the buttons at the ends can stay wired and simply do
 *  nothing. */
export function moveStep(steps: readonly DraftStep[], index: number, delta: number): DraftStep[] {
  const target = index + delta;
  if (index < 0 || index >= steps.length || target < 0 || target >= steps.length) {
    return [...steps];
  }
  const next = [...steps];
  const [moved] = next.splice(index, 1);
  if (!moved) return [...steps];
  next.splice(target, 0, moved);
  return next;
}

export function removeStep(steps: readonly DraftStep[], index: number): DraftStep[] {
  return steps.filter((_, i) => i !== index);
}

export function updateStep(
  steps: readonly DraftStep[],
  index: number,
  patch: Partial<DraftStep>,
): DraftStep[] {
  return steps.map((step, i) => (i === index ? { ...step, ...patch } : step));
}

/** Split a comma-separated field into a clean list. Empty entries are dropped
 *  so a trailing comma while typing does not produce a blank chip. */
export function parseList(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 12);
}

export function formatList(items: readonly string[]): string {
  return items.join(', ');
}

/** What stops a draft being shared with the team, as translation keys.
 *
 *  Mirrors the two ERROR rules the backend gates on (`cases.has_steps` and
 *  `cases.step_titled`) and nothing else. The WARNING rules are deliberately
 *  absent: a draft missing a "why" should be flagged by the server response,
 *  not greyed out client-side, because it is allowed to be shared. */
export function blockersForSharing(draft: CaseDraft): string[] {
  const blockers: string[] = [];
  if (!draft.title.trim()) blockers.push('cases.editor.blocker.no_title');
  if (draft.steps.length === 0) blockers.push('cases.editor.blocker.no_steps');
  const broken = draft.steps.filter((step) => !step.title.trim() || !step.to.trim());
  if (broken.length) blockers.push('cases.editor.blocker.incomplete_steps');
  const badTarget = draft.steps.filter((step) => step.to.trim() && !isValidTarget(step.to.trim()));
  if (badTarget.length) blockers.push('cases.editor.blocker.bad_target');
  return blockers;
}

/** Whether the draft holds enough to be worth saving at all. */
export function canSave(draft: CaseDraft): boolean {
  return Boolean(draft.title.trim());
}

/** Turn a shipped playbook into a draft, so "start from this one" works on
 *  all 144 of them.
 *
 *  `translate` is passed in rather than imported so this stays pure and
 *  testable. It resolves a playbook's translation key to the reader's own
 *  language, which is the point: the copy has to be text the author can edit,
 *  and a key they cannot read is not that. */
export function draftFromPlaybook(
  playbook: Playbook,
  translate: (key: string | undefined, fallback: string) => string,
): CaseDraft {
  return {
    title: translate(playbook.titleKey, playbook.titleDefault),
    description: translate(playbook.descKey, playbook.descDefault),
    longDescription: translate(playbook.longDescKey, playbook.longDescDefault ?? ''),
    category: playbook.category,
    companyTypes: [...(playbook.companyTypes ?? [])],
    roles: [...(playbook.roles ?? [])],
    estMinutes: playbook.estMinutes,
    // Records where the copy came from. Never a foreign key: the shipped
    // playbooks live in the frontend bundle, so the backend has never seen
    // this id and cannot resolve it.
    sourcePlaybookId: playbook.id,
    // A copy always starts private, whatever the original was. Duplicating a
    // case is the start of a draft, not a second publication.
    isShared: false,
    steps: playbook.steps.map((step: PlaybookStep) => ({
      id: step.id,
      title: translate(step.titleKey, step.titleDefault),
      what: translate(step.whatKey, step.whatDefault),
      why: translate(step.whyKey, step.whyDefault),
      moduleLabel: translate(step.moduleLabelKey, step.moduleLabel),
      to: step.to,
      // A shipped step carries its flow items as objects with an optional
      // translation key; an authored one carries plain text, because the
      // author writes in their own language. Take the label and drop the key.
      inputs: (step.inputs ?? []).map((item) => translate(item.labelKey, item.label)),
      outputs: (step.outputs ?? []).map((item) => translate(item.labelKey, item.label)),
    })),
  };
}

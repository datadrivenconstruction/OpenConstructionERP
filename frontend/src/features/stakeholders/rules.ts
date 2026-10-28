// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The parts of the stakeholder screens that are logic rather than layout:
// what a set of scores will be classified as, which moves a commitment
// offers, what a move still needs before it can be sent, how a frequency is
// written, and how the mandate matrix turns into rows and back.
//
// Nothing here decides a permission. The server classifies, checks the
// mandate and refuses; these functions only preview and collect.

import type {
  AnalysisMethod,
  CommitmentStatus,
  CommitmentTarget,
  Letter,
  MandateRow,
  PlanStatus,
  Scores,
  TransitionInput,
} from './api';
import type { KeyText } from './labels';

/* ── Analysis ─────────────────────────────────────────────────────────── */

/** A form's starting scores: the lowest value of every scale, unchecked for every yes/no. */
export function defaultScores(method: AnalysisMethod): Scores {
  const out: Scores = {};
  for (const d of method.dimensions) out[d.code] = d.type === 'bool' ? false : d.min;
  return out;
}

/**
 * The class the framework's rules give these scores: first matching rule,
 * else the method's default. A preview of what the server will store, read
 * from the same rule data; the server's answer is the one that counts.
 */
export function previewClassification(method: AnalysisMethod, scores: Scores): string | null {
  for (const rule of method.rules) {
    const ok = Object.entries(rule.when).every(([dim, cond]) => {
      const v = scores[dim];
      if (cond.eq !== null && cond.eq !== undefined && v !== cond.eq) return false;
      if (cond.gte !== null && cond.gte !== undefined && !(typeof v === 'number' && v >= cond.gte)) return false;
      if (cond.lte !== null && cond.lte !== undefined && !(typeof v === 'number' && v <= cond.lte)) return false;
      return true;
    });
    if (ok) return rule.classification;
  }
  return method.default;
}

/** Whether the grid can be drawn as a square: two number scales to put on the axes. */
export function gridAxes(method: Pick<AnalysisMethod, 'dimensions'>): { x: string; y: string } | null {
  const ints = method.dimensions.filter((d) => d.type === 'int');
  return ints.length >= 2 ? { y: ints[0]!.code, x: ints[1]!.code } : null;
}

/* ── Commitments ──────────────────────────────────────────────────────── */

/**
 * The moves a commitment offers from each state, in the order the buttons
 * appear. Mirrors `COMMITMENT_FSM` in the backend's fsm.py: it lists what is
 * possible, not who may do it.
 */
export const COMMITMENT_MOVES: Record<CommitmentStatus, CommitmentTarget[]> = {
  proposed: ['agreed', 'withdrawn'],
  agreed: ['in_progress', 'fulfilled', 'breached', 'withdrawn'],
  in_progress: ['fulfilled', 'breached', 'withdrawn'],
  fulfilled: ['verified', 'in_progress'],
  breached: ['in_progress', 'fulfilled', 'withdrawn'],
  verified: [],
  withdrawn: [],
};

export interface TransitionDraft {
  target: CommitmentTarget;
  rationale: string;
  /** The day the stakeholder was told the outcome, as a date input writes it. */
  toldOn: string;
  loopNotRequired: string;
  createRisk: boolean;
}

export type TransitionProblem = 'rationale_required' | 'owner_and_due_required' | 'loop_required';

export const TRANSITION_PROBLEM: Record<TransitionProblem, KeyText> = {
  rationale_required: ['stakeholders.ui.transition.problem.rationale_required', 'Write down the reason.'],
  owner_and_due_required: [
    'stakeholders.ui.transition.problem.owner_and_due_required',
    'Give the commitment an owner and a due date first.',
  ],
  loop_required: [
    'stakeholders.ui.transition.problem.loop_required',
    'Enter the day the stakeholder was told, or why that is not needed.',
  ],
};

/** What a move still needs before it can be sent. The server repeats every check. */
export function transitionProblems(
  draft: TransitionDraft,
  commitment: { owner_user_id: string | null; due_date: string | null; communicated_back_at: string | null },
): TransitionProblem[] {
  const problems: TransitionProblem[] = [];
  if ((draft.target === 'withdrawn' || draft.target === 'breached') && !draft.rationale.trim()) {
    problems.push('rationale_required');
  }
  if (draft.target === 'agreed' && (!commitment.owner_user_id || !commitment.due_date)) {
    problems.push('owner_and_due_required');
  }
  if (
    draft.target === 'verified' &&
    !draft.toldOn &&
    !commitment.communicated_back_at &&
    !draft.loopNotRequired.trim()
  ) {
    problems.push('loop_required');
  }
  return problems;
}

export function toTransitionInput(draft: TransitionDraft): TransitionInput {
  return {
    target: draft.target,
    rationale: draft.rationale.trim(),
    // Noon keeps the calendar day the same in every time zone the record is read in.
    communicated_back_at: draft.target === 'verified' && draft.toldOn ? `${draft.toldOn}T12:00:00Z` : null,
    loop_not_required_rationale: draft.target === 'verified' ? draft.loopNotRequired.trim() : '',
    create_risk: draft.target === 'breached' && draft.createRisk,
  };
}

/* ── Plan items ───────────────────────────────────────────────────────── */

/** The states a plan item can move to from each state; mirrors `PLAN_FSM` in the backend's fsm.py. */
export const PLAN_MOVES: Record<PlanStatus, PlanStatus[]> = {
  planned: ['active', 'cancelled'],
  active: ['paused', 'completed', 'cancelled'],
  paused: ['active', 'completed', 'cancelled'],
  completed: [],
  cancelled: [],
};

/** Where a stakeholder sits, as the form holds it. The server knows exactly these four keys. */
export interface PlaceDraft {
  address: string;
  parcel_ref: string;
  lat: string;
  lon: string;
}

export const PLACE_KEYS = ['address', 'parcel_ref', 'lat', 'lon'] as const;

export function placeDraftOf(geo: Record<string, string> | null | undefined): PlaceDraft {
  return { address: geo?.address ?? '', parcel_ref: geo?.parcel_ref ?? '', lat: geo?.lat ?? '', lon: geo?.lon ?? '' };
}

/** The stored form of a place: empty fields are left out, and nothing at all is null. */
export function placeOf(draft: PlaceDraft): Record<string, string> | null {
  const out: Record<string, string> = {};
  for (const key of PLACE_KEYS) {
    const text = draft[key].trim();
    if (text) out[key] = text;
  }
  return Object.keys(out).length > 0 ? out : null;
}

export function samePlace(a: Record<string, string> | null, b: Record<string, string> | null): boolean {
  return PLACE_KEYS.every((key) => (a?.[key] ?? '') === (b?.[key] ?? ''));
}

const DEGREES = /^-?\d+(\.\d+)?$/;

/** The coordinate the server would refuse: not a plain decimal number, or off the globe. */
export function placeProblem(draft: PlaceDraft): 'lat' | 'lon' | null {
  const off = (text: string, limit: number) => {
    const value = text.trim();
    return value !== '' && (!DEGREES.test(value) || Math.abs(Number(value)) > limit);
  };
  if (off(draft.lat, 90)) return 'lat';
  if (off(draft.lon, 180)) return 'lon';
  return null;
}

/** A stakeholder and everything filed under it, however deep. None of them can become its parent. */
export function withDescendants(rows: ReadonlyArray<{ id: string; parent_stakeholder_id: string | null }>, id: string): Set<string> {
  const found = new Set([id]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const row of rows) {
      if (row.parent_stakeholder_id && found.has(row.parent_stakeholder_id) && !found.has(row.id)) {
        found.add(row.id);
        grew = true;
      }
    }
  }
  return found;
}

/** The states the status field offers: the two a new item may start in, or the current one and its moves. */
export function planStatusOptions(current: PlanStatus | null): PlanStatus[] {
  return current ? [current, ...PLAN_MOVES[current]] : ['planned', 'active'];
}

/* ── Frequency ────────────────────────────────────────────────────────── */

export type FrequencyPreset = 'once' | 'weekly' | 'every_two_weeks' | 'monthly' | 'quarterly' | 'yearly';

/** The recurrence rule each preset stands for, in the subset the backend supports. */
export const FREQUENCY_RULE: Record<FrequencyPreset, string> = {
  once: 'once',
  weekly: 'FREQ=WEEKLY',
  every_two_weeks: 'FREQ=WEEKLY;INTERVAL=2',
  monthly: 'FREQ=MONTHLY',
  quarterly: 'FREQ=MONTHLY;INTERVAL=3',
  yearly: 'FREQ=YEARLY',
};

export const FREQUENCY: Record<FrequencyPreset, KeyText> = {
  once: ['stakeholders.ui.frequency.once', 'Once'],
  weekly: ['stakeholders.ui.frequency.weekly', 'Every week'],
  every_two_weeks: ['stakeholders.ui.frequency.every_two_weeks', 'Every two weeks'],
  monthly: ['stakeholders.ui.frequency.monthly', 'Every month'],
  quarterly: ['stakeholders.ui.frequency.quarterly', 'Every three months'],
  yearly: ['stakeholders.ui.frequency.yearly', 'Every year'],
};

/** The preset a stored rule matches, or null for a rule written some other way. */
export function presetOfFrequency(frequency: string | null | undefined): FrequencyPreset | null {
  const raw = (frequency ?? '').trim();
  if (!raw || raw.toLowerCase() === 'once') return 'once';
  const canonical = raw
    .toUpperCase()
    .replace(/^RRULE:/, '')
    .split(';')
    .filter((part) => part && part !== 'INTERVAL=1')
    .sort()
    .join(';');
  for (const [preset, rule] of Object.entries(FREQUENCY_RULE) as Array<[FrequencyPreset, string]>) {
    if (rule.split(';').sort().join(';') === canonical) return preset;
  }
  return null;
}

/* ── What starts a plan item ──────────────────────────────────────────── */

/** The project events a plan item may wait for. The server accepts exactly these names. */
export const EVENT_TRIGGERS = [
  'project_governance.gate.decided',
  'project_governance.phase.changed',
  'stakeholders.commitment.fulfilled',
] as const;

export type PlanStart = 'schedule' | 'gate' | (typeof EVENT_TRIGGERS)[number];

export const PLAN_START: Record<PlanStart, KeyText> = {
  schedule: ['stakeholders.ui.start.schedule', 'On fixed dates'],
  gate: ['stakeholders.ui.start.gate', 'Each time a gate is submitted for review'],
  'project_governance.gate.decided': ['stakeholders.ui.start.gate_decided', 'Each time a gate is decided'],
  'project_governance.phase.changed': ['stakeholders.ui.start.phase_changed', 'Each time the project enters a new phase'],
  'stakeholders.commitment.fulfilled': ['stakeholders.ui.start.commitment_fulfilled', 'Each time a commitment is fulfilled'],
};

/** What starts a stored item, or null for a trigger this screen does not offer (it is then kept as it is). */
export function planStartOf(item: { trigger_kind: string | null; trigger_ref: string | null } | null | undefined): PlanStart | null {
  if (!item || !item.trigger_kind) return 'schedule';
  if (item.trigger_kind === 'gate') return 'gate';
  const known = EVENT_TRIGGERS.find((name) => name === item.trigger_ref);
  return known ?? null;
}

/**
 * The trigger fields a start stands for. A gate trigger names the code of one
 * gate, or nothing to listen to every gate of the project.
 */
export function triggerOf(start: PlanStart, storedGateRef = ''): { trigger_kind: 'gate' | 'event' | null; trigger_ref: string } {
  if (start === 'schedule') return { trigger_kind: null, trigger_ref: '' };
  if (start === 'gate') return { trigger_kind: 'gate', trigger_ref: storedGateRef };
  return { trigger_kind: 'event', trigger_ref: start };
}

/* ── Mandate matrix ───────────────────────────────────────────────────── */

export const LETTERS: Letter[] = ['P', 'D', 'A', 'C', 'I'];

export interface MatrixColumn {
  kind: 'role' | 'body';
  code: string;
}

/** The key of one cell: a decision type against a role or a body, for the whole project. */
export function cellKey(decisionType: string, column: MatrixColumn): string {
  return [decisionType, column.kind, column.code].join('|');
}

/**
 * The letters of the project-wide matrix by cell. Rows with a scope are kept
 * apart: the grid edits the whole-project mandate and must hand scoped rows
 * back untouched.
 */
export function splitMatrix(rows: readonly MandateRow[]): { cells: Record<string, Letter>; scoped: MandateRow[] } {
  const cells: Record<string, Letter> = {};
  const scoped: MandateRow[] = [];
  for (const r of rows) {
    if (r.scope) scoped.push(r);
    else cells[cellKey(r.decision_type, { kind: r.holder_kind, code: r.holder_code })] = r.letter;
  }
  return { cells, scoped };
}

/** The rows a save sends: every lettered cell, then the scoped rows, each with only the fields the server takes. */
export function joinMatrix(
  cells: Record<string, Letter | ''>,
  scoped: readonly MandateRow[],
  notes: readonly MandateRow[] = [],
): MandateRow[] {
  const noteOf = new Map(notes.filter((r) => !r.scope).map((r) => [cellKey(r.decision_type, { kind: r.holder_kind, code: r.holder_code }), r.scope_note]));
  const out: MandateRow[] = [];
  for (const [key, letter] of Object.entries(cells)) {
    if (!letter) continue;
    const [decision_type, holder_kind, holder_code] = key.split('|') as [string, 'role' | 'body', string];
    out.push({ decision_type, scope: '', holder_kind, holder_code, letter, scope_note: noteOf.get(key) ?? '' });
  }
  for (const r of scoped) {
    const scope = r.scope.trim();
    if (!scope) continue;
    out.push({
      decision_type: r.decision_type,
      scope,
      holder_kind: r.holder_kind,
      holder_code: r.holder_code,
      letter: r.letter,
      scope_note: r.scope_note.trim(),
    });
  }
  return out;
}

/** The parts of the project a draft gives more than one decider for one decision, as `[decision type, part]`. */
export function doubleScopedDeciders(scoped: readonly MandateRow[]): Array<[string, string]> {
  const count = new Map<string, number>();
  for (const r of scoped) {
    if (r.letter !== 'D' || !r.scope.trim()) continue;
    const key = [r.decision_type, r.scope.trim()].join('|');
    count.set(key, (count.get(key) ?? 0) + 1);
  }
  return [...count].filter(([, n]) => n > 1).map(([key]) => {
    const at = key.indexOf('|');
    return [key.slice(0, at), key.slice(at + 1)];
  });
}

/** Decision types that have more than one decider in the draft, which the server refuses. */
export function doubleDeciders(cells: Record<string, Letter | ''>): string[] {
  const count = new Map<string, number>();
  for (const [key, letter] of Object.entries(cells)) {
    if (letter !== 'D') continue;
    const type = key.split('|')[0]!;
    count.set(type, (count.get(type) ?? 0) + 1);
  }
  return [...count].filter(([, n]) => n > 1).map(([type]) => type);
}

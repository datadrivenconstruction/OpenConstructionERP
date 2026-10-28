// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The plain logic of the design screens, kept free of React so it is tested
// as functions: which step a record can take next, how the work breakdown
// reads as a tree, what a draft still lacks before it is worth sending, and
// how a form's values become a request body.
//
// Which steps a record offers, and whether the caller may take one, is the
// server's answer (`can` on every row). Nothing here re-derives it.

import type {
  CommentState,
  Deliverable,
  DesignRole,
  Drawing,
  Flag,
  NumberingField,
  NumberingScheme,
  PermitState,
  ReleaseState,
  ReportState,
  ReviewState,
  RoleState,
  Transitions,
  WbsNode,
} from './api';
import type { UiKey } from './text';

/** A move the server offers from the current state, with its flag. */
export interface Step<S extends string> {
  target: S;
  flag: Flag;
}

/** Whether an action exists for the row now. A row without the flag offers nothing. */
export function applies(flag: Flag | null | undefined): flag is Flag {
  return !!flag && flag.applies !== false;
}

/**
 * The moves to draw as buttons, in the order the server lists them. `skip`
 * names the moves that have a button of their own (issuing a release,
 * concluding a review).
 */
export function offered<S extends string>(transitions: Transitions<S> | null | undefined, skip: readonly S[] = []): Step<S>[] {
  const steps: Step<S>[] = [];
  for (const [target, flag] of Object.entries(transitions ?? {}) as Array<[S, Flag | undefined]>) {
    if (applies(flag) && !skip.includes(target)) steps.push({ target, flag });
  }
  return steps;
}

/** The words on the button that moves a record to a state. */
export const STEP_LABEL = {
  release: {
    draft: 'design.ui.step.release.draft',
    ready: 'design.ui.step.release.ready',
    cancelled: 'design.ui.step.release.cancelled',
    issued: 'design.ui.step.release.issued',
  },
  review: {
    planned: 'design.ui.step.review.open',
    open: 'design.ui.step.review.open',
    comments_closed: 'design.ui.step.review.comments_closed',
    concluded: 'design.ui.step.review.concluded',
  },
  comment: {
    open: 'design.ui.step.comment.open',
    answered: 'design.ui.step.comment.answered',
    closed: 'design.ui.step.comment.closed',
    rejected: 'design.ui.step.comment.rejected',
  },
  report: {
    required: 'design.ui.step.report.required',
    commissioned: 'design.ui.step.report.commissioned',
    in_progress: 'design.ui.step.report.in_progress',
    submitted: 'design.ui.step.report.submitted',
    under_check: 'design.ui.step.report.under_check',
    remarks: 'design.ui.step.report.remarks',
    accepted: 'design.ui.step.report.accepted',
    rejected: 'design.ui.step.report.rejected',
    not_required: 'design.ui.step.report.not_required',
  },
  permit: {
    assembling: 'design.ui.step.permit.assembling',
    ready: 'design.ui.step.permit.ready',
    submitted: 'design.ui.step.permit.submitted',
    under_review: 'design.ui.step.permit.under_review',
    remarks: 'design.ui.step.permit.remarks',
    approved: 'design.ui.step.permit.approved',
    partially_approved: 'design.ui.step.permit.partially_approved',
    refused: 'design.ui.step.permit.refused',
    withdrawn: 'design.ui.step.permit.withdrawn',
  },
} as const satisfies {
  release: Record<ReleaseState, UiKey>;
  review: Record<ReviewState, UiKey>;
  comment: Record<CommentState, UiKey>;
  report: Record<ReportState, UiKey>;
  permit: Record<PermitState, UiKey>;
};

/** The states a role's form may offer: where it is, and the moves the server allows from there. */
export function roleStateChoices(current: RoleState, transitions?: Transitions<RoleState> | null): RoleState[] {
  return [current, ...offered(transitions).filter((s) => s.flag.allowed && s.target !== current).map((s) => s.target)];
}

export interface WbsRow {
  node: WbsNode;
  depth: number;
  /** References of every module on the node, added up. */
  referenceCount: number;
}

function codeParts(code: string): Array<string | number> {
  return code.split(/[.\-/]/).map((part) => (/^\d+$/.test(part) ? Number(part) : part));
}

/** Codes compare part by part, so `1.10` follows `1.9` and not `1.1`. */
export function compareCodes(a: string, b: string): number {
  const pa = codeParts(a);
  const pb = codeParts(b);
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const x = pa[i];
    const y = pb[i];
    if (x === undefined) return -1;
    if (y === undefined) return 1;
    if (x === y) continue;
    if (typeof x === 'number' && typeof y === 'number') return x - y;
    return String(x).localeCompare(String(y));
  }
  return 0;
}

/**
 * The work breakdown as the rows of an indented list: parents before their
 * children, siblings by code. A node whose parent is not in the list is shown
 * at the top level rather than dropped, so nothing the API sent disappears.
 */
export function wbsRows(nodes: WbsNode[]): WbsRow[] {
  const ids = new Set(nodes.map((n) => n.id));
  const children = new Map<string, WbsNode[]>();
  for (const n of nodes) {
    const parent = n.parent_id && ids.has(n.parent_id) ? n.parent_id : '';
    children.set(parent, [...(children.get(parent) ?? []), n]);
  }
  const out: WbsRow[] = [];
  const seen = new Set<string>();
  const walk = (parent: string, depth: number) => {
    const list = [...(children.get(parent) ?? [])].sort(
      (a, b) => a.sort_order - b.sort_order || compareCodes(a.code, b.code),
    );
    for (const node of list) {
      if (seen.has(node.id)) continue;
      seen.add(node.id);
      const referenceCount = Object.values(node.references ?? {}).reduce((sum, n) => sum + Number(n || 0), 0);
      out.push({ node, depth, referenceCount });
      walk(node.id, depth + 1);
    }
  };
  walk('', 0);
  return out;
}

/** How many drawings a schedule line has against how many it plans. */
export function deliverableProgress(
  deliverable: Pick<Deliverable, 'id' | 'planned_count'>,
  drawings: Array<Pick<Drawing, 'deliverable_id'>>,
): { linked: number; planned: number } {
  return {
    linked: drawings.filter((d) => d.deliverable_id === deliverable.id).length,
    planned: deliverable.planned_count,
  };
}

export type DraftProblem = 'title_required' | 'phase_required' | 'waiver_reason' | 'count_reason';

/** What a schedule line still lacks; the server repeats every check. */
export function deliverableProblems(
  draft: { title: string; phase_code: string; planned_count: number; planned_count_rationale: string; waived: boolean; waived_rationale: string },
  before?: Pick<Deliverable, 'planned_count'> | null,
): DraftProblem[] {
  const problems: DraftProblem[] = [];
  if (!draft.title.trim()) problems.push('title_required');
  if (!draft.phase_code) problems.push('phase_required');
  if (draft.waived && !draft.waived_rationale.trim()) problems.push('waiver_reason');
  if (before && draft.planned_count < before.planned_count && !draft.planned_count_rationale.trim()) {
    problems.push('count_reason');
  }
  return problems;
}

export const DRAFT_PROBLEM: Record<DraftProblem, UiKey> = {
  title_required: 'design.ui.problem.title_required',
  phase_required: 'design.ui.problem.phase_required',
  waiver_reason: 'design.ui.problem.waiver_reason',
  count_reason: 'design.ui.problem.count_reason',
};

/** A report is only marked not required with a written reason. */
export function reportMoveNeedsReason(target: ReportState): boolean {
  return target === 'not_required';
}

/** Answering a comment needs the answer itself. */
export function commentMoveNeedsAnswer(target: CommentState): boolean {
  return target === 'answered';
}

/** The fields of a number a person types; the rest are filled from the role, the phase or the counter. */
export function typedFields(scheme: Pick<NumberingScheme, 'fields'>): NumberingField[] {
  return scheme.fields.filter((f) => f.code !== 'number' && f.source_field === 'input');
}

/** The drawings that can go into a release: only a drawing with a revision has something to send. */
export function releasable(drawings: Drawing[]): Drawing[] {
  return drawings.filter((d) => !!d.current_revision_id && !d.superseded_by_container_id);
}

/** Who a distribution key such as `role:<id>` names, or null when the screen cannot name it. */
export function recipientName(key: string, roles: Array<Pick<DesignRole, 'id' | 'title' | 'code'>>): string | null {
  const [kind, id] = key.split(':');
  if (kind !== 'role' || !id) return null;
  const role = roles.find((r) => r.id === id);
  return role ? role.title || role.code : null;
}

type FormValue = string | boolean | string[];

/**
 * The body of a PATCH: only what the form changed, because the API reads an
 * absent field as "leave it" and a sent one as "set it". An emptied optional
 * field is sent as null.
 */
export function changedFields<T = Record<string, FormValue | null>>(
  before: Record<string, FormValue>,
  after: Record<string, FormValue>,
  nullable: readonly string[] = [],
): T {
  const out: Record<string, FormValue | null> = {};
  for (const [key, value] of Object.entries(after)) {
    const old = before[key];
    const same = Array.isArray(value) && Array.isArray(old) ? value.join('\n') === old.join('\n') : value === old;
    if (same) continue;
    out[key] = value === '' && nullable.includes(key) ? null : value;
  }
  return out as unknown as T;
}

/** The body of a POST: empty optional fields are left out, so the server applies its defaults. */
export function filledFields<T = Record<string, FormValue>>(values: Record<string, FormValue>): T {
  const out: Record<string, FormValue> = {};
  for (const [key, value] of Object.entries(values)) {
    if (value === '' || (Array.isArray(value) && value.length === 0)) continue;
    out[key] = value;
  }
  return out as unknown as T;
}

/** A whole number from a form field, or null when the field does not hold one. */
export function wholeNumber(text: string): number | null {
  const trimmed = text.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  return Number(trimmed);
}

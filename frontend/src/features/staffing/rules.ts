// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The plain rules the staffing forms apply before they send anything, and the
// small mappers the screens share. Each problem is named by the code the
// server would answer with, so the form shows the same sentence the server
// would. Nothing here decides who may do something; that is the server's.

import type {
  LeaveStatus,
  Phase,
  PlanStatus,
  Position,
  SettablePositionStatus,
  StaffingCatalogue,
  TravelStatus,
} from './api';

/**
 * Whether a submission fits the plan's state at all: only a draft or a revision
 * is something one submits. This picks which control the screen shows; whether
 * the caller may use it is the server's flag.
 */
export function planIsSubmittable(status: PlanStatus): boolean {
  return status === 'draft' || status === 'revising';
}

/** The states a position can be moved to by hand now: the ones the server allows, in the order it lists them. */
export function allowedStatusMoves(position: Pick<Position, 'can'>): SettablePositionStatus[] {
  return Object.entries(position.can.status)
    .filter(([, can]) => can.allowed)
    .map(([status]) => status as SettablePositionStatus);
}

export function nextTravelStatuses(status: TravelStatus): TravelStatus[] {
  if (status === 'planned') return ['booked', 'cancelled'];
  if (status === 'booked') return ['done', 'cancelled'];
  return [];
}

export function nextLeaveStatuses(status: LeaveStatus): Array<Exclude<LeaveStatus, 'requested'>> {
  if (status === 'requested') return ['approved', 'cancelled'];
  if (status === 'approved') return ['taken', 'cancelled'];
  return [];
}

/**
 * A decimal the reader typed, as the string the API takes: a comma becomes a
 * point. Returns null when it is not a plain non-negative decimal. The value
 * stays a string end to end; it is never parsed into a float and sent.
 */
export function decimalString(text: string): string | null {
  const s = text.trim().replace(',', '.');
  return /^\d+(\.\d+)?$/.test(s) ? s : null;
}

/** `fte_out_of_range` unless the text is a decimal above 0 and at most 1. */
export function fteProblem(text: string): 'fte_out_of_range' | null {
  const s = decimalString(text);
  if (s === null) return 'fte_out_of_range';
  const [whole = '0', fraction = ''] = s.split('.');
  const wholeNumber = Number(whole);
  const hasFraction = /[1-9]/.test(fraction);
  if (wholeNumber === 0) return hasFraction ? null : 'fte_out_of_range';
  if (wholeNumber === 1) return hasFraction ? 'fte_out_of_range' : null;
  return 'fte_out_of_range';
}

export function headcountProblem(text: string): 'headcount_invalid' | null {
  return /^[1-9]\d*$/.test(text.trim()) ? null : 'headcount_invalid';
}

/** ISO dates compare as strings. An open end is fine. */
export function datesProblem(from: string | null | undefined, to: string | null | undefined): 'exit_before_entry' | null {
  return from && to && to < from ? 'exit_before_entry' : null;
}

/** The number field of a document takes the last four characters only; a full number must never be typed in. */
export function last4Problem(text: string): 'full_number_rejected' | null {
  return text.trim().length > 4 ? 'full_number_rejected' : null;
}

/** A cost needs a currency, and a cost is a non-negative decimal. */
export function costProblem(cost: string, currency: string): 'cost_invalid' | 'currency_required' | null {
  if (!cost.trim()) return null;
  if (decimalString(cost) === null) return 'cost_invalid';
  return currency.trim().length === 3 ? null : 'currency_required';
}

/**
 * The phases a plan can have positions in, in the order the server lists them with the pinned catalogue. A phase
 * only an existing position carries comes last. The client holds no list of its own.
 */
export function phasesOf(catalogue: StaffingCatalogue | null | undefined, positions: Position[] = []): Phase[] {
  const seen = new Set<Phase>(catalogue?.phases ?? []);
  for (const position of positions) seen.add(position.phase);
  return [...seen];
}

/** What a key role can be required before: the vocabulary the server sends, plus the tag already set. */
export function requirementTags(catalogue: StaffingCatalogue, current?: string | null): Array<{ tag: string; resolvable: boolean }> {
  const options = [...catalogue.required_before_options];
  if (current && !options.some((o) => o.tag === current)) options.push({ tag: current, resolvable: false });
  return options;
}

/** Positions per phase in the given phase order, phases without positions left out. */
export function groupByPhase(positions: Position[], phases: Phase[]): Array<{ phase: Phase; positions: Position[] }> {
  return phases
    .map((phase) => ({ phase, positions: positions.filter((p) => p.phase === phase) }))
    .filter((g) => g.positions.length > 0);
}

/** The roles of the catalogue that are used in a phase and not planned there yet. */
export function rolesNotPlanned(catalogue: StaffingCatalogue, positions: Position[], phase: Phase) {
  const planned = new Set(
    positions.filter((p) => p.phase === phase && p.status !== 'cancelled').map((p) => p.role_code),
  );
  return catalogue.roles.filter((r) => r.phases.includes(phase) && !planned.has(r.code));
}

/** The people who can still be handed over from: live assignments, proposed or confirmed. */
export function liveFills(positions: Position[]) {
  return positions.flatMap((p) => p.fills.filter((f) => f.status !== 'ended').map((fill) => ({ position: p, fill })));
}

/** How many decimals an FTE or FTE-day figure needs on screen: at least one, at most two, no padding zeros. */
export function fteDecimals(value: string | null | undefined): 1 | 2 {
  const fraction = (value ?? '').split('.')[1] ?? '';
  return fraction.replace(/0+$/, '').length > 1 ? 2 : 1;
}

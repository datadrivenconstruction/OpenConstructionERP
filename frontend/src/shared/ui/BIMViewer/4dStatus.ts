/**
 * 4dStatus.ts — pure helpers for the 4D timeline scrubber.
 *
 * Given a date, an element id, and the full activity set, resolve what the
 * element's status is at that point in time.  Kept free of React / Three.js
 * so it is trivially unit-testable.
 *
 * Status model:
 *   · `not_started` — the earliest linked activity starts AFTER `date`.
 *   · `in_progress` — `date` falls inside the [start, end] window of at
 *                     least one linked activity.
 *   · `completed`   — every linked activity has ended before `date`.
 *   · `unlinked`    — the element has zero schedule activities linked to it
 *                     (render untouched — the 4D mode leaves it alone).
 *
 * When multiple activities cover the same element, the one with the
 * earliest start among overlapping activities wins (per spec).  That
 * matches the intuition that the element "becomes active" the moment
 * the earliest trade touches it and stays active as long as any trade
 * is still working on it.
 */

export type FourDStatus =
  | 'not_started'
  | 'in_progress'
  | 'completed'
  | 'unlinked';

/** Minimal shape the resolver needs — a trimmed-down projection of the
 *  schedule Activity type so callers can pass whatever they have without
 *  pulling in cross-feature types. */
export interface FourDActivity {
  id: string;
  name: string;
  start_date: string | null;
  end_date: string | null;
}

/** Parse an ISO date string (or the first 10 chars of one) into a UTC
 *  millisecond timestamp.  Returns `null` for empty / malformed input so
 *  callers can skip the activity without throwing. */
export function parseDate(s: string | null | undefined): number | null {
  if (!s) return null;
  // Normalise `YYYY-MM-DD` style strings (no time) to UTC midnight so two
  // activities sharing the same day compare equal regardless of the local
  // timezone the browser is running in.
  const trimmed = s.length >= 10 ? s.slice(0, 10) : s;
  const ms = Date.parse(trimmed);
  return Number.isFinite(ms) ? ms : null;
}

/** Resolve the status of a single activity at time `t`.
 *
 *  Semantics match the spec:
 *    · t  < start  → not_started
 *    · t == start  → in_progress
 *    · start <= t <= end → in_progress
 *    · t  > end   → completed
 */
export function resolveActivityStatus(
  activity: FourDActivity,
  t: number,
): Exclude<FourDStatus, 'unlinked'> {
  const start = parseDate(activity.start_date);
  const end = parseDate(activity.end_date);
  if (start != null && t < start) return 'not_started';
  if (end != null && t > end) return 'completed';
  // Any in-window / start-only / end-only activity counts as active at t.
  return 'in_progress';
}

/**
 * Resolve the aggregate status of a BIM element at time `t`, given:
 *   · `elementId` — the element to resolve status for.
 *   · `activityLinks` — map of `elementId → activityId[]`.
 *   · `activitiesById` — map of activity id → FourDActivity.
 *
 * If the element has no entries in `activityLinks`, returns `'unlinked'`.
 *
 * Otherwise iterates every linked activity and returns:
 *   · `'in_progress'` if any activity is in-progress at t.
 *   · `'not_started'` if every activity is not-started.
 *   · `'completed'` otherwise (mix of completed / not_started where no
 *     activity is currently active — this is the "work is about to
 *     resume later" case which the spec treats as 'not_started' IF
 *     every activity is still ahead, else 'completed').
 *
 * Tie-breaking when activities overlap: the earliest-starting activity
 * wins, which only matters when building the activeActivity label (the
 * status itself is determined by the union of windows).
 */
export function resolveElementStatus(
  elementId: string,
  t: number,
  activityLinks: ReadonlyMap<string, readonly string[]>,
  activitiesById: ReadonlyMap<string, FourDActivity>,
): FourDStatus {
  const linkedIds = activityLinks.get(elementId);
  if (!linkedIds || linkedIds.length === 0) return 'unlinked';

  let anyInProgress = false;
  let anyNotStarted = false;
  let anyCompleted = false;

  for (const actId of linkedIds) {
    const act = activitiesById.get(actId);
    if (!act) continue;
    const s = resolveActivityStatus(act, t);
    if (s === 'in_progress') anyInProgress = true;
    else if (s === 'not_started') anyNotStarted = true;
    else if (s === 'completed') anyCompleted = true;
  }

  if (anyInProgress) return 'in_progress';
  if (anyCompleted && !anyNotStarted) return 'completed';
  if (anyNotStarted && !anyCompleted) return 'not_started';
  // Mixed completed + not_started (no overlap either side of `t`) —
  // intuitively we're between phases: treat as 'completed' so the user
  // sees progress, not a regression.
  if (anyCompleted && anyNotStarted) return 'completed';
  // No valid linked activity (every id missing or malformed dates) →
  // the element has links on paper but nothing actionable → treat as
  // unlinked so it renders normally.
  return 'unlinked';
}

/** Return the name of the activity that best represents "what's active
 *  right now" at time t — the earliest-starting in-progress activity.
 *  Falls back to the next upcoming activity, then to any completed
 *  activity.  Returns `null` when the element has no linked activities
 *  at all (i.e. unlinked). */
export function pickActiveActivityName(
  t: number,
  activities: readonly FourDActivity[],
): string | null {
  if (activities.length === 0) return null;

  let bestInProgress: FourDActivity | null = null;
  let bestInProgressStart = Infinity;
  let nextUpcoming: FourDActivity | null = null;
  let nextUpcomingStart = Infinity;
  let lastCompleted: FourDActivity | null = null;
  let lastCompletedEnd = -Infinity;

  for (const act of activities) {
    const start = parseDate(act.start_date);
    const end = parseDate(act.end_date);
    const s = resolveActivityStatus(act, t);
    if (s === 'in_progress') {
      if (start != null && start < bestInProgressStart) {
        bestInProgressStart = start;
        bestInProgress = act;
      } else if (bestInProgress == null) {
        bestInProgress = act;
      }
    } else if (s === 'not_started') {
      if (start != null && start < nextUpcomingStart) {
        nextUpcomingStart = start;
        nextUpcoming = act;
      }
    } else if (s === 'completed') {
      if (end != null && end > lastCompletedEnd) {
        lastCompletedEnd = end;
        lastCompleted = act;
      }
    }
  }

  if (bestInProgress) return bestInProgress.name;
  if (nextUpcoming) return nextUpcoming.name;
  if (lastCompleted) return lastCompleted.name;
  return null;
}

/** Compute the schedule [startDate, endDate] bounds from a list of
 *  activities.  Returns `null` for either bound if no activity has a
 *  valid date on that side. */
export function computeScheduleBounds(
  activities: readonly FourDActivity[],
): { startMs: number | null; endMs: number | null } {
  let minStart: number | null = null;
  let maxEnd: number | null = null;
  for (const act of activities) {
    const s = parseDate(act.start_date);
    const e = parseDate(act.end_date);
    if (s != null && (minStart == null || s < minStart)) minStart = s;
    if (e != null && (maxEnd == null || e > maxEnd)) maxEnd = e;
  }
  return { startMs: minStart, endMs: maxEnd };
}

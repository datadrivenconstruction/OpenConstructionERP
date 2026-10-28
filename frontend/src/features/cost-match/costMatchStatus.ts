// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The pure decisions the cost-match screen makes for itself.
 *
 * They live apart from the panel deliberately. Importing the panel pulls in the
 * shared UI barrel, which transitively boots i18next with the whole English
 * resource, and a vitest worker that does that never answers. The type imports
 * below are erased at compile time, so this module has no runtime dependency on
 * anything.
 *
 * Two of these carry the module's whole point. `adoptedItem` answers what the
 * project actually took from a line, which after an override is *not* the
 * suggestion the row still carries. `tallyResults` answers how much is left to
 * do, where every zero is a real answer rather than a missing one.
 */

import type { MatchCandidate, MatchDecision, MatchLineInput, MatchResult } from './api';

/* ── Vocabulary ────────────────────────────────────────────────────────── */

/**
 * The four tiers, ordered the way a reviewer works through them: what the
 * machine is sure about first, what it is not claiming at all last.
 */
export const TIER_ORDER = ['exact', 'high_confidence', 'needs_review', 'unmatched'] as const;
export type MatchTier = (typeof TIER_ORDER)[number];

export const DECISION_STATE_ORDER = ['pending', 'confirmed', 'overridden', 'rejected'] as const;
export type DecisionState = (typeof DECISION_STATE_ORDER)[number];

/**
 * The tiers the review queue is made of.
 *
 * Mirrors `repository.QUEUE_TIERS`. Exact and confident lines still need
 * confirming — nothing is auto-applied — but they are not what the queue is
 * for, and the two lists have to agree or the badge lies about the work.
 */
export const QUEUE_TIERS: readonly MatchTier[] = ['needs_review', 'unmatched'];

/**
 * The matcher's own confidence bands (backend `matcher.py`).
 *
 * Deliberately not the platform's shared `CONFIDENCE_HIGH_MIN` / `_MEDIUM_MIN`
 * (0.8 / 0.5): those are provisional cutoffs for a different scorer. Passing a
 * cost-match confidence to `ConfidenceBadge`'s `score` prop would re-threshold
 * every row against them and repaint answers the backend already banded.
 */
export const HIGH_CONFIDENCE = 0.75;
export const REVIEW_CONFIDENCE = 0.45;

export type BadgeTone = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

/** The traffic light the matcher itself uses, as `ConfidenceBadge` names it. */
export type ConfidenceBand = 'high' | 'medium' | 'low';

/* ── Confidence ────────────────────────────────────────────────────────── */

/**
 * A confidence as a number, from the plain-decimal string it arrives as.
 *
 * Zero is a real answer — nothing scored — so an unreadable or absent value
 * lands on the same 0 rather than on a sentinel. That is the honest collapse
 * here: both mean "this row claims nothing", and there is no third rendering
 * for them to disagree about.
 */
export function confidenceValue(raw: string | null | undefined): number {
  if (raw === null || raw === undefined || raw === '') return 0;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : 0;
}

/** A confidence as whole percent, for display only. */
export function confidencePercent(raw: string | null | undefined): number {
  return Math.round(confidenceValue(raw) * 100);
}

/**
 * The traffic-light band of a stored confidence.
 *
 * Mirrors `service._band`, read off the same two constants, so a stored result
 * is never shown in a different colour from the one the scorer meant. Both
 * boundaries are inclusive: exactly 0.75 is high, exactly 0.45 is medium.
 */
export function confidenceBand(raw: string | null | undefined): ConfidenceBand {
  const value = confidenceValue(raw);
  if (value >= HIGH_CONFIDENCE) return 'high';
  if (value >= REVIEW_CONFIDENCE) return 'medium';
  return 'low';
}

/**
 * Where a scored line lands, from its confidence alone.
 *
 * Mirrors `service._tier_for`. `exact` needs both the word-for-word equality
 * the matcher reports in `factors.exact` **and** a confidence that survived the
 * unit check: an exact text match priced per cubic metre against a line
 * measured in square metres is not an exact match, and the matcher's unit
 * penalty is what pushes it back down into review.
 *
 * With no candidate the answer is `unmatched` whatever the number says.
 */
export function tierForConfidence(
  raw: string | null | undefined,
  opts: { hasSuggestion: boolean; exact?: number },
): MatchTier {
  if (!opts.hasSuggestion) return 'unmatched';
  const value = confidenceValue(raw);
  if (value < REVIEW_CONFIDENCE) return 'unmatched';
  if (value >= HIGH_CONFIDENCE) {
    return typeof opts.exact === 'number' && opts.exact >= 1 ? 'exact' : 'high_confidence';
  }
  return 'needs_review';
}

/**
 * The tier of one result, narrowed to something this screen can render.
 *
 * The server's own `tier` wins whenever it is a value we know, because it is
 * the record of what the matcher decided and re-deriving it would let the two
 * disagree. A value we do not know is re-derived rather than rendered raw: an
 * unrecognised enum reaching the DOM is an untranslated string in the middle of
 * a translated screen.
 */
export function resultTier(
  result: Pick<MatchResult, 'tier' | 'confidence' | 'suggested_cost_item_id' | 'factors'>,
): MatchTier {
  if ((TIER_ORDER as readonly string[]).includes(result.tier)) {
    return result.tier as MatchTier;
  }
  const factors = result.factors ?? {};
  return tierForConfidence(result.confidence, {
    hasSuggestion: result.suggested_cost_item_id !== null,
    exact: typeof factors.exact === 'number' ? factors.exact : undefined,
  });
}

/**
 * How a tier is painted.
 *
 * Only `exact` earns the success colour. A confident match is still a proposal
 * nobody has accepted, and painting it green would have the screen vouching for
 * something the record does not.
 */
export function tierTone(tier: MatchTier): BadgeTone {
  switch (tier) {
    case 'exact':
      return 'success';
    case 'high_confidence':
      return 'blue';
    case 'needs_review':
      return 'warning';
    case 'unmatched':
      return 'neutral';
  }
}

/* ── The human pass ────────────────────────────────────────────────────── */

/** The decision state of a result, narrowed the same way as its tier. */
export function decisionStateOf(result: Pick<MatchResult, 'decision_state'>): DecisionState {
  if ((DECISION_STATE_ORDER as readonly string[]).includes(result.decision_state)) {
    return result.decision_state as DecisionState;
  }
  return 'pending';
}

/**
 * How a decision state is painted.
 *
 * `rejected` is neutral rather than an error: ruling that nothing in this base
 * fits is a real and useful answer, and it takes the line out of the queue
 * without inventing a rate for it. `pending` is the warning, because that is
 * the state with work outstanding.
 */
export function decisionTone(state: DecisionState): BadgeTone {
  switch (state) {
    case 'pending':
      return 'warning';
    case 'confirmed':
      return 'success';
    case 'overridden':
      return 'blue';
    case 'rejected':
      return 'neutral';
  }
}

/**
 * The ruling in force on a result, or null while it is pending.
 *
 * Sorted by `seq` rather than trusted in array order. The backend does order
 * the history — and by the persisted sequence, not by timestamp, so two rulings
 * written in the same microsecond keep their order — but the answer here is
 * "the last ruling", and reading that off an array's tail makes this file
 * depend on a promise made in another one.
 */
export function currentDecision(result: Pick<MatchResult, 'decisions'>): MatchDecision | null {
  const history = result.decisions ?? [];
  if (history.length === 0) return null;
  // `?? null` rather than a non-null assertion: the length guard above already
  // rules the undefined out, but an index read is typed as possibly absent and
  // the honest narrowing costs nothing.
  return [...history].sort((a, b) => a.seq - b.seq)[history.length - 1] ?? null;
}

/** The cost item a line ended up priced against. */
export interface AdoptedItem {
  costItemId: string;
  code: string;
  description: string;
  unit: string;
  /** Plain-decimal string, or null where the base carries no usable rate. */
  rate: string | null;
  currency: string;
  /** The ruling that adopted it, as the backend spelled it. */
  decision: string;
  seq: number;
}

/**
 * What the project actually took from this line, or null if it took nothing.
 *
 * The one function on this screen that must not be guessed from the row. After
 * an override, `suggested_code` still holds what the machine proposed, and a
 * panel that keeps rendering it shows a cost item the reviewer explicitly
 * refused. The ruling's own snapshot is the answer.
 *
 * There is no branch on the kind of ruling and there must not be one. A
 * confirmation copies the suggestion into the same `decided_*` columns an
 * override writes (`service.record_decision`), and a rejection leaves them
 * empty, exactly like a line nobody has ruled on. So "is there a decided cost
 * item id" answers all four states at once, and two paths that could drift
 * apart never exist.
 */
export function adoptedItem(result: Pick<MatchResult, 'decisions'>): AdoptedItem | null {
  const decision = currentDecision(result);
  if (!decision || !decision.decided_cost_item_id) return null;
  return {
    costItemId: decision.decided_cost_item_id,
    code: decision.decided_code,
    description: decision.decided_description,
    unit: decision.decided_unit,
    rate: decision.decided_rate,
    currency: decision.decided_currency,
    decision: decision.decision,
    seq: decision.seq,
  };
}

/**
 * Whether this line still stands between the bill and a price.
 *
 * The queue predicate the backend pages on: one of the two tiers where the
 * machine is not claiming an answer, and nobody has ruled yet.
 */
export function needsPerson(
  result: Pick<MatchResult, 'tier' | 'confidence' | 'suggested_cost_item_id' | 'factors' | 'decision_state'>,
): boolean {
  return (
    QUEUE_TIERS.includes(resultTier(result)) && decisionStateOf(result) === 'pending'
  );
}

/**
 * Whether "confirm" is an available ruling on this line.
 *
 * False when the base returned no candidate: there is nothing to confirm, and
 * the endpoint answers 422. The honest rulings there are an override onto an
 * item the reviewer found themselves, or a rejection.
 */
export function canConfirm(result: Pick<MatchResult, 'suggested_cost_item_id'>): boolean {
  return result.suggested_cost_item_id !== null;
}

/**
 * The runners-up worth offering as an override target.
 *
 * The winner is kept in `alternatives` on purpose, so the reviewer sees it
 * beside what it beat — but it is not an *override* target: overriding onto the
 * item already suggested would be accepted and would file a confirmation under
 * the wrong word in the audit trail. A candidate with no cost item id cannot be
 * a target at all, since the ruling is made by id.
 */
export function overrideOptions(
  result: Pick<MatchResult, 'alternatives' | 'suggested_cost_item_id'>,
): MatchCandidate[] {
  return (result.alternatives ?? []).filter(
    (candidate) =>
      !!candidate.cost_item_id && candidate.cost_item_id !== result.suggested_cost_item_id,
  );
}

/* ── Derived counts and grouping ───────────────────────────────────────── */

/** One tier's worth of results, in the order a reviewer works through them. */
export interface TierGroup {
  tier: MatchTier;
  items: MatchResult[];
}

/**
 * Results grouped by tier, in `TIER_ORDER`, empty tiers omitted.
 *
 * Order inside a group is left exactly as it arrived, which is submission
 * order: a reviewer reads a bill down the page, not by score.
 */
export function groupByTier(results: MatchResult[]): TierGroup[] {
  const buckets = new Map<MatchTier, MatchResult[]>();
  for (const result of results) {
    const tier = resultTier(result);
    const bucket = buckets.get(tier);
    if (bucket) bucket.push(result);
    else buckets.set(tier, [result]);
  }
  return TIER_ORDER.filter((tier) => buckets.has(tier)).map((tier) => ({
    tier,
    items: buckets.get(tier) ?? [],
  }));
}

/** Every figure this screen derives from a set of results it already holds. */
export interface ResultTally {
  total: number;
  exact: number;
  high_confidence: number;
  needs_review: number;
  unmatched: number;
  pending: number;
  confirmed: number;
  overridden: number;
  rejected: number;
  queueLength: number;
}

/**
 * Count a set of results by tier and by ruling.
 *
 * Every field is present and zero on an empty set, deliberately: a screen that
 * renders an absent count as blank and a real zero as blank cannot tell "no
 * rejections" from "we did not look". Mirrors `service._counts_from_groups`,
 * but over the rows in hand rather than the whole run — the run's own counts
 * come from the server, which sees rows this page does not.
 */
export function tallyResults(results: MatchResult[]): ResultTally {
  const tally: ResultTally = {
    total: 0,
    exact: 0,
    high_confidence: 0,
    needs_review: 0,
    unmatched: 0,
    pending: 0,
    confirmed: 0,
    overridden: 0,
    rejected: 0,
    queueLength: 0,
  };
  for (const result of results) {
    const tier = resultTier(result);
    const state = decisionStateOf(result);
    tally.total += 1;
    tally[tier] += 1;
    tally[state] += 1;
    if (QUEUE_TIERS.includes(tier) && state === 'pending') tally.queueLength += 1;
  }
  return tally;
}

/* ── Reading a pasted bill ─────────────────────────────────────────────── */

/** What one paste turned into, and what it cost to get there. */
export interface ParsedBill {
  lines: MatchLineInput[];
  /** Lines past the cap, which the request cannot carry. */
  overflow: number;
  /** Lines whose quantity column could not be read as a number. */
  unreadableQuantity: number;
}

const COLUMN_SEPARATOR = /\t|;|\|/;

/**
 * Read a quantity out of a bill's own notation.
 *
 * Bills are pasted from a spreadsheet in whatever locale wrote them, so "1,5",
 * "1.234,56" and "1 234.56" all mean a number here. The rule is the usual one:
 * whichever of `,` and `.` comes last is the decimal separator and the other is
 * grouping. Anything left over is not a quantity.
 *
 * A negative quantity comes back null rather than negative. The schema declares
 * `quantity` as `ge=0`, so one credit line would 422 the entire batch of five
 * hundred; dropping the figure and keeping the line is the smaller loss, and
 * the count of them is reported to the person pasting.
 */
function readQuantity(raw: string): { value: string | null; readable: boolean } {
  const trimmed = raw.trim();
  if (trimmed === '') return { value: null, readable: true };
  // Only \s here: it already covers U+00A0 and U+202F, which used to be
  // spelled out beside it. Naming them again read as "these are extra" and
  // cost an eslint no-irregular-whitespace error for nothing.
  const stripped = trimmed.replace(/\s/g, '');
  const lastComma = stripped.lastIndexOf(',');
  const lastDot = stripped.lastIndexOf('.');
  let normalised = stripped;
  if (lastComma >= 0 && lastDot >= 0) {
    normalised =
      lastComma > lastDot
        ? stripped.replace(/\./g, '').replace(',', '.')
        : stripped.replace(/,/g, '');
  } else if (lastComma >= 0) {
    normalised = stripped.replace(',', '.');
  }
  if (!/^-?\d+(\.\d+)?$/.test(normalised)) return { value: null, readable: false };
  if (normalised.startsWith('-')) return { value: null, readable: false };
  return { value: normalised, readable: true };
}

/**
 * Turn a pasted bill into the lines the run endpoint takes.
 *
 * Columns are tab, semicolon or pipe separated — what a spreadsheet and a CSV
 * actually produce — and read as description, unit, quantity, then the
 * subcontractor's own item code. A row with no separator is all description,
 * which is the common case of a column pasted on its own.
 *
 * Blank rows in the middle are kept. A bill really does contain header-only and
 * empty rows, the schema allows a blank description on purpose, and dropping
 * them here would hide from the reviewer that the paste had holes in it. Only
 * trailing blank rows go, since those are an artefact of the paste itself.
 */
export function parseBillLines(text: string, max = 500): ParsedBill {
  const rows = (text ?? '').split(/\r\n|\r|\n/);
  while (rows.length > 0 && (rows[rows.length - 1] ?? '').trim() === '') rows.pop();

  const lines: MatchLineInput[] = [];
  let unreadableQuantity = 0;
  for (const row of rows) {
    const cells = row.split(COLUMN_SEPARATOR);
    const quantity = readQuantity(cells[2] ?? '');
    if (!quantity.readable) unreadableQuantity += 1;
    lines.push({
      description: (cells[0] ?? '').trim(),
      unit: (cells[1] ?? '').trim(),
      quantity: quantity.value,
      source_ref: (cells[3] ?? '').trim(),
    });
  }

  return {
    lines: lines.slice(0, max),
    overflow: Math.max(0, lines.length - max),
    unreadableQuantity,
  };
}

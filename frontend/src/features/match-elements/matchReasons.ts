// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pure, DB-free helpers behind the /match-elements review worklist.
//
// Three things the review UI needs, kept out of the components so they
// stay testable without a browser or a network:
//
//   1. Lane partitioning - split a session's groups into the three
//      confidence lanes (needs-you / quick-review / auto-confirmed) and
//      sort each lane worst-first so the riskiest work floats to the top.
//   2. Plain-language reasons - turn a candidate's ``boosts_applied``
//      map + ``reasoning`` note + raw semantic score into a short list of
//      human sentences ("matched the unit", "same trade", "matching
//      size", "overlapping keywords") the estimator can read in a second.
//   3. Prior-pick correlation - line a group's signature up against the
//      caller's saved template library so we can badge "you mapped this
//      before" and mark the exact candidate that was picked last time.
//
// The lane and confirmable rules mirror the backend exactly: only a
// group with ``status === 'suggested'`` and a ranked candidate can be
// bulk-accepted (see MatchService.bulk_confirm, which filters on that
// status), so ``isConfirmable`` gates the per-lane accept button the
// same way.

import type { ConfidenceBand, GroupStatus } from './api';

// ─────────────────────────────────────────────────────────────────────
//  Lanes
// ─────────────────────────────────────────────────────────────────────

/** The three review lanes, ordered worst-first (the order they render). */
export type MatchLaneId = 'needs_you' | 'quick_review' | 'auto_confirmed';

/** Worst-first render order: outstanding work sits above the safe pile. */
export const MATCH_LANE_ORDER: readonly MatchLaneId[] = [
  'needs_you',
  'quick_review',
  'auto_confirmed',
] as const;

/** The minimal group shape the lane maths reads. A real ``GroupSummary``
 *  is a structural superset, so callers pass it straight through. */
export interface LaneGroupInput {
  status: GroupStatus;
  confidence_band: ConfidenceBand;
  /** Numeric confidence serialised as a string (or null before a run). */
  confidence: string | null;
  suggested_code: string | null;
}

// Statuses where a human (or auto-confirm) has already settled the group.
// These park in the auto-confirmed lane so the two review lanes only ever
// show work that is still open.
const RESOLVED_STATUSES: ReadonlySet<GroupStatus> = new Set<GroupStatus>([
  'confirmed',
  'applied',
  'overridden',
  'skipped',
]);

/** True when the group has already been settled by a person or auto-confirm. */
export function isResolvedStatus(status: GroupStatus): boolean {
  return RESOLVED_STATUSES.has(status);
}

/** True when a per-lane bulk-accept would actually confirm this group.
 *  Matches the backend gate: only ``suggested`` groups that carry a ranked
 *  candidate get confirmed. */
export function isConfirmable(g: LaneGroupInput): boolean {
  return g.status === 'suggested' && !!g.suggested_code;
}

/** Assign a group to one of the three lanes.
 *
 * Resolved groups are settled → auto-confirmed lane. Groups with no ranked
 * candidate (unmatched) or a deferred decision (tbd) always need a person →
 * needs-you. Everything else is a live ``suggested`` group whose confidence
 * band decides: high → auto-confirmed, medium → quick-review, low/none →
 * needs-you.
 */
export function laneForGroup(g: LaneGroupInput): MatchLaneId {
  if (isResolvedStatus(g.status)) return 'auto_confirmed';
  if (g.status === 'unmatched' || g.status === 'tbd' || !g.suggested_code) {
    return 'needs_you';
  }
  if (g.confidence_band === 'high') return 'auto_confirmed';
  if (g.confidence_band === 'medium') return 'quick_review';
  return 'needs_you';
}

// Fallback ordering when a group carries no numeric confidence yet - keeps
// the sort stable and still band-aware.
const BAND_RANK: Record<ConfidenceBand, number> = {
  none: 0,
  low: 0.34,
  medium: 0.67,
  high: 0.9,
};

/** Worst-first sort key within a lane. Lower sorts first (needs attention
 *  soonest). Resolved groups get a +1 offset so already-handled rows sink
 *  below the outstanding work in the auto-confirmed lane. */
export function groupSortKey(g: LaneGroupInput): number {
  const numeric = g.confidence != null ? Number(g.confidence) : Number.NaN;
  const base = Number.isFinite(numeric) ? numeric : BAND_RANK[g.confidence_band];
  return isResolvedStatus(g.status) ? base + 1 : base;
}

/** Partition groups into the three lanes, each sorted worst-first. Pure -
 *  returns fresh arrays and never mutates the input. */
export function partitionLanes<T extends LaneGroupInput>(
  groups: readonly T[],
): Record<MatchLaneId, T[]> {
  const out: Record<MatchLaneId, T[]> = {
    needs_you: [],
    quick_review: [],
    auto_confirmed: [],
  };
  for (const g of groups) out[laneForGroup(g)].push(g);
  for (const id of MATCH_LANE_ORDER) {
    out[id].sort((a, b) => groupSortKey(a) - groupSortKey(b));
  }
  return out;
}

/** The group_keys a per-lane accept should send: only the confirmable
 *  (``suggested`` + candidate) groups in that lane. */
export function confirmableKeys<T extends LaneGroupInput & { group_key: string }>(
  laneGroups: readonly T[],
): string[] {
  return laneGroups.filter(isConfirmable).map((g) => g.group_key);
}

// ─────────────────────────────────────────────────────────────────────
//  Plain-language reasons
// ─────────────────────────────────────────────────────────────────────

export type ReasonTone = 'positive' | 'negative' | 'neutral';

/** One plain-language reason a candidate ranked where it did. The component
 *  renders ``t(i18nKey, { defaultValue: defaultLabel, ...vars })`` so the
 *  helper stays free of React / i18n. */
export interface MatchReason {
  /** Stable id (deduplication + React key + test assertions). */
  id: string;
  i18nKey: string;
  defaultLabel: string;
  tone: ReasonTone;
  vars?: Record<string, string | number>;
}

/** The subset of a candidate the reason builder reads. ``reasoning`` is
 *  present on the wire (backend MatchCandidate) even though the current
 *  api.ts type omits it, so it is optional here and read defensively. */
export interface ReasonCandidateInput {
  boosts_applied?: Record<string, number> | null;
  vector_score?: number | null;
  reasoning?: string | null;
  unit?: string | null;
}

/** A raw semantic (vector) score at or above this is worth surfacing as a
 *  "strong description match" when no keyword-overlap boost already fired. */
export const STRONG_SEMANTIC_MIN = 0.62;

interface BoostMeta {
  /** Reason id - shared by mutually-exclusive keys (e.g. unit match vs
   *  mismatch) so only one unit reason is ever shown. */
  id: string;
  i18nKey: string;
  /** Default label when the boost delta is positive. Empty = never shown positive. */
  positive: string;
  /** Default label when the delta is negative (a penalty). */
  negative?: string;
  negativeKey?: string;
}

// Only keys we can phrase for a human are mapped; anything else is skipped
// so a raw boost key never leaks into the UI. Keys mirror the emitters in
// app/core/match_service/boosts/* and the resources / exact-code paths.
const BOOST_META: Record<string, BoostMeta> = {
  exact_code: {
    id: 'exact_code',
    i18nKey: 'match.reason.exact_code',
    positive: 'Exact catalogue code',
  },
  unit_match: {
    id: 'unit',
    i18nKey: 'match.reason.unit',
    positive: 'Matched the expected unit',
  },
  unit_mismatch: {
    id: 'unit',
    i18nKey: 'match.reason.unit',
    positive: '',
    negative: 'Unit does not match',
    negativeKey: 'match.reason.unit_mismatch',
  },
  classifier_match: {
    id: 'trade',
    i18nKey: 'match.reason.trade',
    positive: 'Same classification and trade',
  },
  classifier_group_match: {
    id: 'trade',
    i18nKey: 'match.reason.trade_group',
    positive: 'Same trade group',
  },
  soft_ost_category: {
    id: 'category',
    i18nKey: 'match.reason.category',
    positive: 'Same element category',
  },
  soft_material_class: {
    id: 'material',
    i18nKey: 'match.reason.material',
    positive: 'Same material',
  },
  soft_nominal_size_mm: {
    id: 'size',
    i18nKey: 'match.reason.size',
    positive: 'Matching size',
  },
  resources_token_set: {
    id: 'terms',
    i18nKey: 'match.reason.terms',
    positive: 'Overlapping keywords',
  },
  region_match: {
    id: 'region',
    i18nKey: 'match.reason.region',
    positive: 'Local rate for your region',
  },
};

// Deterministic, "most explainable first" order. The four the estimator
// cares about most - unit, trade, size, term overlap - lead.
const REASON_ORDER: readonly string[] = [
  'exact_code',
  'unit_match',
  'unit_mismatch',
  'classifier_match',
  'classifier_group_match',
  'soft_nominal_size_mm',
  'soft_material_class',
  'soft_ost_category',
  'resources_token_set',
  'region_match',
] as const;

/** Build the ordered, de-duplicated list of plain-language reasons a
 *  candidate ranked where it did, from its boost map, semantic score and
 *  optional model note. Pure. */
export function buildMatchReasons(cand: ReasonCandidateInput): MatchReason[] {
  const reasons: MatchReason[] = [];
  const seen = new Set<string>();
  const push = (r: MatchReason): void => {
    if (seen.has(r.id)) return;
    seen.add(r.id);
    reasons.push(r);
  };

  const boosts = cand.boosts_applied ?? {};
  const unit = (cand.unit ?? '').trim();

  for (const key of REASON_ORDER) {
    const delta = boosts[key];
    if (delta == null || delta === 0) continue;
    const meta = BOOST_META[key];
    if (!meta) continue;
    const negative = delta < 0;
    const label = negative ? meta.negative : meta.positive;
    if (!label) continue;

    // The unit reason names the unit when we have one ("Matched unit m2").
    let i18nKey = negative ? meta.negativeKey ?? meta.i18nKey : meta.i18nKey;
    let defaultLabel = label;
    let vars: Record<string, string | number> | undefined;
    if (meta.id === 'unit' && !negative && unit) {
      i18nKey = 'match.reason.unit_named';
      defaultLabel = 'Matched unit {{unit}}';
      vars = { unit };
    }

    push({ id: meta.id, i18nKey, defaultLabel, tone: negative ? 'negative' : 'positive', vars });
  }

  // No keyword boost fired but the semantic match is strong on its own -
  // surface that as the term-overlap reason so a good vector hit still
  // explains itself.
  const vs = typeof cand.vector_score === 'number' ? cand.vector_score : Number.NaN;
  if (Number.isFinite(vs) && vs >= STRONG_SEMANTIC_MIN && !seen.has('terms')) {
    push({
      id: 'semantic',
      i18nKey: 'match.reason.semantic',
      defaultLabel: 'Strong description match',
      tone: 'positive',
    });
  }

  return reasons;
}

/** The "your saved mapping picked this before" reason. Built separately
 *  because the count comes from the template library, not the candidate. */
export function priorConfirmReason(useCount: number): MatchReason {
  return {
    id: 'prior',
    i18nKey: 'match.reason.prior_confirmed',
    defaultLabel: 'You confirmed this match {{count}}x before',
    tone: 'positive',
    vars: { count: useCount },
  };
}

/** The free-text model note (LLM re-rank ``reasoning``) when present and
 *  non-empty, else null. Reads the optional wire field defensively. */
export function reasoningText(cand: { reasoning?: string | null }): string | null {
  const r = (cand.reasoning ?? '').trim();
  return r.length > 0 ? r : null;
}

// ─────────────────────────────────────────────────────────────────────
//  Prior-pick (template library) correlation
// ─────────────────────────────────────────────────────────────────────

/** The template fields the prior-pick badge reads - a real ``MatchTemplate``
 *  is a structural superset. */
export interface TemplateHitInput {
  signature: string;
  use_count: number;
  last_used_at: string | null;
  cwicr_position_id: string;
}

/** Index a template list by signature for O(1) group lookup. The library
 *  is ordered by use_count desc, so the first (most-used) row wins on the
 *  rare duplicate-signature case. */
export function indexTemplatesBySignature<T extends { signature: string }>(
  templates: readonly T[],
): Map<string, T> {
  const idx = new Map<string, T>();
  for (const t of templates) {
    if (t.signature && !idx.has(t.signature)) idx.set(t.signature, t);
  }
  return idx;
}

/** The saved template for a group's signature, or null when the group has
 *  never been mapped before (or carries no signature). */
export function priorPickForSignature<T extends { signature: string }>(
  signature: string | null | undefined,
  index: Map<string, T>,
): T | null {
  if (!signature) return null;
  return index.get(signature) ?? null;
}

/** True when this candidate is the exact catalogue row the saved template
 *  picked last time (so it gets the "you mapped this before" badge). */
export function isPriorPickCandidate(
  candidateId: string | null | undefined,
  prior: Pick<TemplateHitInput, 'cwicr_position_id'> | null | undefined,
): boolean {
  return !!prior && !!candidateId && candidateId === prior.cwicr_position_id;
}

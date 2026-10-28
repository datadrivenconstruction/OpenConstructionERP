// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// OpenConstructionERP — DataDrivenConstruction (DDC)
// AI Estimate Builder — conversational intake v2 (pure helpers).
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pure, side-effect-free helpers for the intake panel. Everything here is
// deterministic and unit-tested (answer serialization, warning mapping,
// round-state reducer, coverage badges). No React, no network, no i18n
// resolution — only key + params mapping so the component owns translation.

import type {
  ComposedPackage,
  CoverageBand,
  DependencyWarning,
  IntakePhase,
  IntakeQuestion,
  IntakeState,
  QuestionKind,
} from './types';

// ── Answer serialization ─────────────────────────────────────────────────────

/**
 * Coerce a raw control value into the typed shape the backend expects for a
 * given question kind.
 *
 * - `number` / `length`: a finite number, or null when blank / unparseable
 *   (the backend treats a missing required param as "asked but unanswered",
 *   never as zero).
 * - `bool`: a real boolean (accepts the string forms a `<select>` emits).
 * - `choice`: the string value as-is (empty string -> null so an unselected
 *   choice is not sent as a confirmed empty answer).
 *
 * Returning `null` (rather than dropping the key) lets the caller decide
 * whether a required answer is still missing.
 */
export function serializeAnswerValue(kind: QuestionKind, raw: unknown): unknown {
  if (raw === undefined || raw === null) return null;

  if (kind === 'number' || kind === 'length') {
    if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null;
    const s = String(raw).trim().replace(',', '.');
    if (s === '') return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  }

  if (kind === 'bool') {
    if (typeof raw === 'boolean') return raw;
    const s = String(raw).trim().toLowerCase();
    if (s === '' ) return null;
    return s === 'true' || s === 'yes' || s === '1' || s === 'on';
  }

  // choice
  const s = String(raw).trim();
  return s === '' ? null : s;
}

/**
 * Serialize a draft answer map (param_key -> raw control value) into the
 * `answers` payload for `POST /intake/answer`.
 *
 * Only keys present in `questions` are serialized (so stale draft entries from
 * a previous round never leak), and `null` results are omitted so an
 * unanswered optional question is not persisted as a confirmed blank.
 */
export function serializeAnswers(
  questions: IntakeQuestion[],
  draft: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const q of questions) {
    if (!(q.param_key in draft)) continue;
    const value = serializeAnswerValue(q.kind, draft[q.param_key]);
    if (value === null) continue;
    out[q.param_key] = value;
  }
  return out;
}

/**
 * The set of required questions in the current batch that are still
 * unanswered (no serialized value in the draft). Used to gate the "Continue"
 * button: an empty result means the round can advance.
 */
export function unansweredRequired(
  questions: IntakeQuestion[],
  draft: Record<string, unknown>,
): string[] {
  const missing: string[] = [];
  for (const q of questions) {
    if (!q.required) continue;
    const raw = q.param_key in draft ? draft[q.param_key] : q.current_value;
    if (serializeAnswerValue(q.kind, raw) === null) missing.push(q.param_key);
  }
  return missing;
}

/**
 * Seed a draft answer map from the questions' prefilled `current_value`s so
 * the controls open showing what the extractor already knew. Values are kept
 * raw (the control coerces on change); only defined values are seeded.
 */
export function seedDraftFromQuestions(
  questions: IntakeQuestion[],
): Record<string, unknown> {
  const draft: Record<string, unknown> = {};
  for (const q of questions) {
    if (q.current_value !== undefined && q.current_value !== null) {
      draft[q.param_key] = q.current_value;
    }
  }
  return draft;
}

// ── Warning mapping ──────────────────────────────────────────────────────────

/** A dependency warning mapped to an i18n key + interpolation params. */
export interface MappedWarning {
  /** A stable key for React lists (unique per successor/prerequisite pair). */
  id: string;
  /** The i18n key (always `aiest.dep.missing_prereq`). */
  i18nKey: string;
  /** Interpolation params for `t(key, { defaultValue, ...params })`. */
  params: {
    prereq: string;
    successor: string;
    successor_stage: string;
    prerequisite_stage: string;
  };
  /** The English default with `{{prereq}}` interpolation for `defaultValue`. */
  defaultValue: string;
}

/**
 * Map the backend's raw `dependency_warnings` onto i18n-ready notes. These are
 * always NON-blocking yellow notes; this helper only shapes them for render.
 *
 * The defaultValue mirrors the design's wording and uses i18next `{{prereq}}`
 * interpolation so a translator can reorder the sentence per locale.
 */
export function mapDependencyWarnings(
  warnings: DependencyWarning[] | undefined | null,
): MappedWarning[] {
  if (!Array.isArray(warnings)) return [];
  return warnings.map((w) => ({
    id: `${w.successor}::${w.prerequisite}`,
    i18nKey: w.code || 'aiest.dep.missing_prereq',
    params: {
      prereq: w.prerequisite,
      successor: w.successor,
      successor_stage: w.successor_stage,
      prerequisite_stage: w.prerequisite_stage,
    },
    defaultValue:
      'This stage usually requires {{prereq}} which is not in the estimate yet',
  }));
}

// ── Round-state reducer ──────────────────────────────────────────────────────

/**
 * The visible, derived shape of a round used by the dialogue panel. Pure
 * projection of an IntakeState — no hidden state, so it is trivially testable.
 */
export interface RoundView {
  /** 1-based round number for display ("Round 1 of up to 3"). */
  roundNumber: number;
  /** Hard ceiling on clarification rounds (founder decision 1). */
  maxRounds: number;
  /** Whether the current phase is one of the clarify_round_* phases. */
  inRound: boolean;
  /** Whether the dialogue is on the parameter sheet (checkpoint A). */
  onParameterSheet: boolean;
  /** Whether the dialogue is on the editable group board (checkpoint B). */
  onGroupBoard: boolean;
  /** Whether extraction / compose is running (no questions yet). */
  isWorking: boolean;
  /** Whether the intake has bridged to the run pipeline. */
  isDone: boolean;
  /** The current round's questions (empty off-round). */
  questions: IntakeQuestion[];
}

const CLARIFY_PHASES: ReadonlySet<IntakePhase> = new Set([
  'clarify_round_1',
  'clarify_round_2',
  'clarify_round_3',
]);

const WORKING_PHASES: ReadonlySet<IntakePhase> = new Set([
  'collect_request',
  'extract',
  'compose_groups',
]);

export const MAX_INTAKE_ROUNDS = 3;

/**
 * Project an IntakeState into the RoundView the panel renders. Clamps the
 * round number to [1, maxRounds] so a backend that over-counts can never
 * render "Round 4 of 3" (the 3-round cap is also enforced server-side).
 */
export function deriveRoundView(state: IntakeState | null): RoundView {
  if (!state) {
    return {
      roundNumber: 1,
      maxRounds: MAX_INTAKE_ROUNDS,
      inRound: false,
      onParameterSheet: false,
      onGroupBoard: false,
      isWorking: false,
      isDone: false,
      questions: [],
    };
  }
  const inRound = CLARIFY_PHASES.has(state.phase);
  // round_idx is 0-based count of rounds already consumed; the active round is
  // round_idx + 1, clamped to the cap so display never exceeds the ceiling.
  const roundNumber = Math.min(
    MAX_INTAKE_ROUNDS,
    Math.max(1, (state.round_idx ?? 0) + 1),
  );
  return {
    roundNumber,
    maxRounds: MAX_INTAKE_ROUNDS,
    inRound,
    onParameterSheet: state.phase === 'parameter_sheet',
    onGroupBoard: state.phase === 'group_board',
    isWorking: WORKING_PHASES.has(state.phase) && state.questions.length === 0,
    isDone: state.phase === 'done',
    questions: inRound ? state.questions : [],
  };
}

/**
 * Whether a third (final) advancing answer would exhaust the round budget.
 * Used to label the Continue button "Build estimate" on the last round so the
 * user knows there is no fourth round (the cap is enforced by the server).
 */
export function isFinalRound(state: IntakeState | null): boolean {
  if (!state) return false;
  if (!CLARIFY_PHASES.has(state.phase)) return false;
  return (state.rounds_remaining ?? MAX_INTAKE_ROUNDS) <= 1;
}

// ── Coverage / confidence display ────────────────────────────────────────────

/** Badge variant for a package coverage band (maps to shared Badge variants). */
export function coverageVariant(
  band: CoverageBand,
): 'success' | 'warning' | 'error' {
  switch (band) {
    case 'grounded':
      return 'success';
    case 'weak':
      return 'warning';
    case 'gap':
    default:
      return 'error';
  }
}

/** The i18n key + English default for a coverage band label. */
export function coverageLabel(band: CoverageBand): {
  i18nKey: string;
  defaultValue: string;
} {
  switch (band) {
    case 'grounded':
      return { i18nKey: 'aiest.coverage.grounded', defaultValue: 'Grounded' };
    case 'weak':
      return { i18nKey: 'aiest.coverage.weak', defaultValue: 'Weak match' };
    case 'gap':
    default:
      return { i18nKey: 'aiest.coverage.gap', defaultValue: 'No catalogue match' };
  }
}

/**
 * Format a real probe score as a percent string, or a localisation-free dash
 * when the score is null (honest: never a fake 0% or 50% placeholder).
 */
export function scorePercent(score: number | null | undefined): string {
  if (score === null || score === undefined || !Number.isFinite(score)) return '—';
  return `${Math.round(Math.max(0, Math.min(1, score)) * 100)}%`;
}

/** Format a detected-type confidence: percent, or the "selected" label when null. */
export function typeConfidenceLabel(confidence: number | null | undefined): {
  i18nKey: string | null;
  defaultValue: string;
} {
  if (confidence === null || confidence === undefined || !Number.isFinite(confidence)) {
    return { i18nKey: 'aiest.type.selected', defaultValue: 'Selected' };
  }
  return { i18nKey: null, defaultValue: scorePercent(confidence) };
}

// ── Package board grouping ───────────────────────────────────────────────────

/** Ordered foreman stages — the board reads top-to-bottom in build order. */
export const FOREMAN_STAGES = [
  'demo',
  'structure',
  'rough',
  'close',
  'finish',
  'commission',
] as const;

export type ForemanStage = (typeof FOREMAN_STAGES)[number];

const STAGE_INDEX: Record<string, number> = FOREMAN_STAGES.reduce(
  (acc, s, i) => {
    acc[s] = i;
    return acc;
  },
  {} as Record<string, number>,
);

/** The earliest foreman stage a package spans (drives its board position). */
export function primaryStage(pkg: ComposedPackage): ForemanStage {
  let best: ForemanStage = 'finish';
  let bestIdx = STAGE_INDEX['finish'] ?? FOREMAN_STAGES.length;
  for (const s of pkg.stages) {
    const idx = STAGE_INDEX[s];
    if (idx !== undefined && idx < bestIdx) {
      bestIdx = idx;
      best = s as ForemanStage;
    }
  }
  return best;
}

export interface StageGroup {
  stage: ForemanStage;
  packages: ComposedPackage[];
}

/**
 * Group composed packages by their primary foreman stage, in build order, so
 * the board renders demo -> structure -> rough -> close -> finish ->
 * commission. Stages with no packages are omitted.
 */
export function groupPackagesByStage(packages: ComposedPackage[]): StageGroup[] {
  const buckets = new Map<ForemanStage, ComposedPackage[]>();
  for (const pkg of packages) {
    const stage = primaryStage(pkg);
    const list = buckets.get(stage) ?? [];
    list.push(pkg);
    buckets.set(stage, list);
  }
  const out: StageGroup[] = [];
  for (const stage of FOREMAN_STAGES) {
    const list = buckets.get(stage);
    if (list && list.length > 0) {
      // Stable: grounded first, then weak, then gap, then alphabetical.
      list.sort((a, b) => {
        const order: Record<CoverageBand, number> = { grounded: 0, weak: 1, gap: 2 };
        const d = order[a.coverage] - order[b.coverage];
        if (d !== 0) return d;
        return a.package_key.localeCompare(b.package_key);
      });
      out.push({ stage, packages: list });
    }
  }
  return out;
}

/** Coverage tallies for the board footer ("14 grounded, 3 weak, 1 gap"). */
export interface CoverageTally {
  total: number;
  grounded: number;
  weak: number;
  gap: number;
}

/** Count coverage bands across the SELECTED packages only. */
export function coverageTally(packages: ComposedPackage[]): CoverageTally {
  const tally: CoverageTally = { total: 0, grounded: 0, weak: 0, gap: 0 };
  for (const pkg of packages) {
    if (!pkg.selected) continue;
    tally.total += 1;
    tally[pkg.coverage] += 1;
  }
  return tally;
}

// ── Mode / degradation ───────────────────────────────────────────────────────

/** Whether the intake is on the offline (no-AI) curated-form path. */
export function isOfflineMode(state: IntakeState | null): boolean {
  if (!state) return false;
  return state.mode === 'offline' || state.degraded_reason === 'no_ai_key';
}

/** A human-readable i18n key + default for a degraded_reason banner. */
export function degradedMessage(reason: string | null | undefined): {
  i18nKey: string;
  defaultValue: string;
} | null {
  switch (reason) {
    case 'no_ai_key':
      return {
        i18nKey: 'aiest.degraded.no_ai_key',
        defaultValue:
          'AI conversation is off; using the guided form. Grounded matching still works.',
      };
    case 'no_vectors':
      return {
        i18nKey: 'aiest.degraded.no_vectors',
        defaultValue:
          'The cost database has no vectors loaded; packages will show as gaps you can fill manually.',
      };
    case 'no_catalogue':
      return {
        i18nKey: 'aiest.degraded.no_catalogue',
        defaultValue:
          'No cost catalogue is bound for this currency or region; rates cannot be matched yet.',
      };
    default:
      return null;
  }
}

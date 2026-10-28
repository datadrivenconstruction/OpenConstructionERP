// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// Estimate Copilot — pure step model and progression logic.
//
// The copilot chains four capabilities the platform already exposes over HTTP
// into one guided path: a rough conceptual number, a scope-coverage check, a
// quality audit, and the written basis-of-estimate. This file owns only the
// ordering and the gating rules; it has no React and no network code so it can
// be unit tested in isolation.
//
// Progression is modelled as a single `confirmedCount` (0..N) = how many
// leading steps the user has confirmed. Because the UI only ever lets the user
// confirm the one active step, the confirmed steps are always a contiguous
// prefix, which this integer captures exactly. From it we derive which step is
// active, which are locked, and whether the flow is complete.

/** The four ordered steps of the guided flow. */
export type CopilotStepId = 'conceptual' | 'scope' | 'audit' | 'basis';

/** Per-step lifecycle within the guided flow. */
export type StepPhase = 'locked' | 'active' | 'confirmed';

/** Static definition of one step: its order and its i18n labels. */
export interface CopilotStepDef {
  id: CopilotStepId;
  /** Zero-based position in the sequence. */
  order: number;
  /** i18n key + English fallback for the step title. */
  titleKey: string;
  titleFallback: string;
  /** i18n key + English fallback for the short explanation. */
  descKey: string;
  descFallback: string;
  /** i18n key + English fallback for the "run this step" button. */
  ctaKey: string;
  ctaFallback: string;
}

/**
 * The ordered step definitions. Order in this array is the source of truth for
 * the flow sequence; `order` mirrors the index for convenience.
 */
export const COPILOT_STEPS: readonly CopilotStepDef[] = [
  {
    id: 'conceptual',
    order: 0,
    titleKey: 'copilot.step.conceptual.title',
    titleFallback: 'Conceptual estimate',
    descKey: 'copilot.step.conceptual.desc',
    descFallback:
      'Get a fast first-pass number for the whole project before detailing anything.',
    ctaKey: 'copilot.step.conceptual.cta',
    ctaFallback: 'Run conceptual estimate',
  },
  {
    id: 'scope',
    order: 1,
    titleKey: 'copilot.step.scope.title',
    titleFallback: 'Scope coverage',
    descKey: 'copilot.step.scope.desc',
    descFallback: 'Check the bill of quantities for missing trades and work packages.',
    ctaKey: 'copilot.step.scope.cta',
    ctaFallback: 'Check scope coverage',
  },
  {
    id: 'audit',
    order: 2,
    titleKey: 'copilot.step.audit.title',
    titleFallback: 'Quality audit',
    descKey: 'copilot.step.audit.desc',
    descFallback: 'Run the estimate through the quality rule checks for errors and warnings.',
    ctaKey: 'copilot.step.audit.cta',
    ctaFallback: 'Run quality audit',
  },
  {
    id: 'basis',
    order: 3,
    titleKey: 'copilot.step.basis.title',
    titleFallback: 'Basis of estimate',
    descKey: 'copilot.step.basis.desc',
    descFallback:
      'Generate the written basis-of-estimate documenting assumptions and inclusions.',
    ctaKey: 'copilot.step.basis.cta',
    ctaFallback: 'Generate basis of estimate',
  },
] as const;

/** Total number of steps in the guided flow. */
export const COPILOT_STEP_COUNT = COPILOT_STEPS.length;

/** Zero-based index of a step id, or -1 when the id is unknown. */
export function indexOfStep(id: CopilotStepId): number {
  return COPILOT_STEPS.findIndex((s) => s.id === id);
}

/** The step definition at an index, or `null` when out of range. */
export function stepAt(index: number): CopilotStepDef | null {
  if (!Number.isInteger(index) || index < 0 || index >= COPILOT_STEP_COUNT) return null;
  return COPILOT_STEPS[index] ?? null;
}

/** Clamp any number to a valid confirmed-count in [0, COPILOT_STEP_COUNT]. */
export function clampConfirmedCount(count: number): number {
  // NaN is meaningless -> 0. A finite or infinite number falls through to the
  // range clamp below: +Infinity floors above the max and saturates to it,
  // -Infinity floors below 0 and pins to 0.
  if (Number.isNaN(count)) return 0;
  const n = Math.floor(count);
  if (n < 0) return 0;
  if (n > COPILOT_STEP_COUNT) return COPILOT_STEP_COUNT;
  return n;
}

/**
 * Index of the currently active step, or -1 when every step is confirmed.
 *
 * The active step is always the first not-yet-confirmed step, which - because
 * confirmations are a contiguous prefix - equals `confirmedCount`.
 */
export function activeStepIndex(confirmedCount: number): number {
  const c = clampConfirmedCount(confirmedCount);
  return c >= COPILOT_STEP_COUNT ? -1 : c;
}

/** Id of the currently active step, or `null` when the flow is complete. */
export function activeStepId(confirmedCount: number): CopilotStepId | null {
  const idx = activeStepIndex(confirmedCount);
  return idx === -1 ? null : (COPILOT_STEPS[idx]?.id ?? null);
}

/** Lifecycle phase of the step at `index` given the confirmed count. */
export function stepPhase(index: number, confirmedCount: number): StepPhase {
  const c = clampConfirmedCount(confirmedCount);
  if (index < c) return 'confirmed';
  if (index === c) return 'active';
  return 'locked';
}

/** Lifecycle phase of a step by id. Unknown ids are treated as locked. */
export function stepPhaseById(id: CopilotStepId, confirmedCount: number): StepPhase {
  const idx = indexOfStep(id);
  if (idx === -1) return 'locked';
  return stepPhase(idx, confirmedCount);
}

/**
 * Whether the step at `index` may be confirmed right now. Only the single
 * active step is confirmable; already-confirmed and still-locked steps are not.
 */
export function canConfirm(index: number, confirmedCount: number): boolean {
  return index === activeStepIndex(confirmedCount);
}

/** Whether a step (by id) may be confirmed right now. */
export function canConfirmStep(id: CopilotStepId, confirmedCount: number): boolean {
  const idx = indexOfStep(id);
  if (idx === -1) return false;
  return canConfirm(idx, confirmedCount);
}

/**
 * Advance the flow after confirming the active step. Returns the next confirmed
 * count, never exceeding the total. Idempotent once complete.
 */
export function confirmStep(confirmedCount: number): number {
  return clampConfirmedCount(clampConfirmedCount(confirmedCount) + 1);
}

/**
 * Re-open an earlier step for a redo. Confirming a step commits every step
 * before it, so revisiting an already-confirmed step rolls the flow back to
 * that step (its later confirmations no longer hold). Revisiting the active or
 * a locked step is a no-op.
 */
export function revisitStep(id: CopilotStepId, confirmedCount: number): number {
  const idx = indexOfStep(id);
  if (idx === -1) return clampConfirmedCount(confirmedCount);
  return Math.min(clampConfirmedCount(confirmedCount), idx);
}

/** True once every step has been confirmed. */
export function isComplete(confirmedCount: number): boolean {
  return clampConfirmedCount(confirmedCount) >= COPILOT_STEP_COUNT;
}

/** Whole-number completion percentage in [0, 100]. */
export function progressPercent(confirmedCount: number): number {
  const c = clampConfirmedCount(confirmedCount);
  return Math.round((c / COPILOT_STEP_COUNT) * 100);
}

// ── Persistence ──────────────────────────────────────────────────────────────
//
// The flow is saved per project so a reload lands the user back on the step
// they were on. Everything here is pure (key building + defensive parsing); the
// React hook owns the actual localStorage reads and writes.

/**
 * Storage schema version. Bump it when {@link CopilotPersistedState} changes so
 * an entry written by an older layout is ignored rather than misread.
 */
export const COPILOT_STORAGE_VERSION = 1;

/** Versioned localStorage key prefix for the persisted copilot flow. */
export const COPILOT_STORAGE_PREFIX = `oe.copilot.flow.v${COPILOT_STORAGE_VERSION}`;

/**
 * Build the per-project localStorage key, or `null` when no project is selected
 * (nothing to persist against). Keying by project id scopes saved progress to
 * one project; the stored {@link CopilotPersistedState.boqId} then guards
 * against restoring progress that belongs to a different BOQ in that project.
 */
export function copilotStorageKey(projectId: string | null | undefined): string | null {
  if (!projectId) return null;
  return `${COPILOT_STORAGE_PREFIX}:${projectId}`;
}

/** Persisted, per-project snapshot of the guided flow. */
export interface CopilotPersistedState {
  /** How many leading steps the user has confirmed (0..COPILOT_STEP_COUNT). */
  confirmedCount: number;
  /** Ids of steps that have produced a result at least once. */
  ranSteps: CopilotStepId[];
  /** BOQ the progress belongs to; used to reject a cross-BOQ restore. */
  boqId: string | null;
}

/** The set of known step ids, for validating untrusted stored values. */
const KNOWN_STEP_IDS: ReadonlySet<string> = new Set<string>(COPILOT_STEPS.map((s) => s.id));

/** Narrow an untrusted value to a known {@link CopilotStepId}. */
function isKnownStepId(value: unknown): value is CopilotStepId {
  return typeof value === 'string' && KNOWN_STEP_IDS.has(value);
}

/**
 * Filter an untrusted value into the known step ids it contains, preserving
 * order and dropping duplicates and anything unrecognised. Non-arrays yield an
 * empty list. Never throws.
 */
export function sanitizeRanSteps(raw: unknown): CopilotStepId[] {
  if (!Array.isArray(raw)) return [];
  const out: CopilotStepId[] = [];
  for (const value of raw) {
    if (isKnownStepId(value) && !out.includes(value)) out.push(value);
  }
  return out;
}

/**
 * Coerce an untrusted parsed value (typically from localStorage) into a valid
 * {@link CopilotPersistedState}, or `null` when it is not a usable object.
 * `confirmedCount` is clamped via {@link clampConfirmedCount}, `ranSteps` is
 * filtered to known ids, and a non-string `boqId` becomes `null`. Never throws.
 */
export function parsePersistedState(raw: unknown): CopilotPersistedState | null {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return null;
  const obj = raw as Record<string, unknown>;
  return {
    confirmedCount: clampConfirmedCount(Number(obj.confirmedCount)),
    ranSteps: sanitizeRanSteps(obj.ranSteps),
    boqId: typeof obj.boqId === 'string' ? obj.boqId : null,
  };
}

// ── Readiness ────────────────────────────────────────────────────────────────
//
// The readiness summary answers one question at a glance: is the estimate ready
// to review? A step counts as "done" once confirmed; the estimate is
// review-ready once every step is confirmed (which, because a step can only be
// confirmed after producing a result, also means every step has been run).

/** Readiness of one step for the summary panel. */
export interface StepReadiness {
  id: CopilotStepId;
  order: number;
  phase: StepPhase;
  /** The user has confirmed this step. */
  confirmed: boolean;
  /** This step has produced a result (a confirmed step always has). */
  hasResult: boolean;
}

/** Derived readiness of the whole guided flow for the summary panel. */
export interface FlowReadiness {
  steps: StepReadiness[];
  /** Number of confirmed (done) steps. */
  confirmedCount: number;
  /** Number of steps that have produced a result. */
  ranCount: number;
  total: number;
  /**
   * True once every step is confirmed. Because a step can only be confirmed
   * after it has produced a result, this also implies every step has been run.
   */
  reviewReady: boolean;
}

/**
 * Derive the flow's readiness from the confirmed count and the ids of steps
 * that have produced a result. A step is "done" when confirmed; the estimate is
 * review-ready once all steps are confirmed. Pure - drives the summary panel.
 */
export function deriveReadiness(
  confirmedCount: number,
  ranStepIds: readonly CopilotStepId[] = [],
): FlowReadiness {
  const c = clampConfirmedCount(confirmedCount);
  const ran = new Set<CopilotStepId>(ranStepIds);
  const steps: StepReadiness[] = COPILOT_STEPS.map((def) => {
    const phase = stepPhase(def.order, c);
    const confirmed = phase === 'confirmed';
    return {
      id: def.id,
      order: def.order,
      phase,
      confirmed,
      // Confirmed steps have a result by construction; otherwise consult the
      // ran set (which may carry a result restored from a previous session).
      hasResult: confirmed || ran.has(def.id),
    };
  });
  return {
    steps,
    confirmedCount: c,
    ranCount: steps.filter((s) => s.hasResult).length,
    total: COPILOT_STEP_COUNT,
    reviewReady: isComplete(c),
  };
}

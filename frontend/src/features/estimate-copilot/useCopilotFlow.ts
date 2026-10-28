// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// Estimate Copilot — flow controller.
//
// Thin orchestration over four capabilities the platform already exposes over
// HTTP. This hook owns the React Query mutations, the conceptual step's ROM
// inputs, the per-step confirm state, and its persistence to localStorage (per
// project, so a reload lands the user back on the step they were on); the
// ordering/gating/readiness/persistence rules live in `steps.ts` (pure, unit
// tested).
//
// Endpoints chained:
//   1. conceptual  POST /api/v1/rom-estimate/generate/        (rough first-pass number)
//   2. scope       POST /api/v1/boq/boqs/{boqId}/check-scope/ (missing trades / work packages)
//   3. audit       POST /api/v1/validation/run/               (quality rule checks)
//   4. basis       POST /api/v1/estimate-basis/generate       (written basis-of-estimate)
//
// Steps 1 and 4 reuse the feature clients (rom-estimate, estimate-basis); steps
// 2 and 3 post directly, since the copilot only consumes a slice of each result.
//
// Money fields arrive as Decimal strings on the wire; they are kept as strings
// and only ever formatted (never float-mathed) in the view.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';

import { apiPost } from '@/shared/lib/api';
import {
  generateBasis,
  type EstimateBasisDocument,
  type QualificationItem,
} from '@/features/estimate-basis/api';
import {
  romEstimateApi,
  type RomEstimateResult,
  type RomReference,
} from '@/features/rom-estimate/api';
import {
  COPILOT_STEPS,
  type CopilotPersistedState,
  type CopilotStepDef,
  type CopilotStepId,
  type FlowReadiness,
  type StepPhase,
  activeStepId as activeStepIdFor,
  canConfirmStep,
  confirmStep as confirmStepCount,
  copilotStorageKey,
  deriveReadiness,
  indexOfStep,
  isComplete as isCompleteFor,
  parsePersistedState,
  progressPercent,
  revisitStep,
  stepPhaseById,
} from './steps';

/**
 * Rule sets applied by the quality audit. `boq_quality` is the universal
 * catch-all (zero prices, missing quantities, duplicates, unrealistic rates)
 * and `project_completeness` checks trade coverage. The audit endpoint flags
 * any set it cannot run under `unsupported_rule_sets` rather than failing.
 */
export const DEFAULT_AUDIT_RULE_SETS = ['boq_quality', 'project_completeness'] as const;

// ── Wire shapes (local, minimal) ──────────────────────────────────────────

/**
 * The conceptual step reuses the ROM (order-of-magnitude) calculator, so its
 * result is the calculator's own {@link RomEstimateResult}. The alias keeps the
 * copilot's public type name stable for existing importers while pointing at the
 * real wire shape (headline `total`, `currency`, `cost_per_m2`, `accuracy` band).
 */
export type ConceptualEstimateResult = RomEstimateResult;

/** One missing scope item flagged by the coverage check. */
export interface ScopeMissingItem {
  description: string;
  category: string;
  priority: 'high' | 'medium' | 'low';
  reason: string;
  estimated_rate: number;
  unit: string;
}

/** Response of POST /v1/boq/boqs/{boqId}/check-scope/. */
export interface ScopeCoverageResult {
  completeness_score: number;
  missing_items: ScopeMissingItem[];
  warnings: string[];
  summary: string;
  model_used: string;
  tokens_used: number;
}

/** Response of POST /v1/validation/run/ (only the fields the copilot shows). */
export interface QualityAuditResult {
  report_id: string;
  status: 'passed' | 'warnings' | 'errors' | 'skipped';
  score: number;
  total_rules: number;
  passed_count: number;
  warning_count: number;
  error_count: number;
  info_count: number;
  rule_sets: string[];
  unsupported_rule_sets?: string[];
  duration_ms: number;
}

/** One section of the written basis-of-estimate. */
export interface BasisSection {
  title: string;
  body: string;
}

/** Compact summary of a basis-of-estimate the copilot renders. Typed defensively. */
export interface BasisOfEstimateResult {
  narrative?: string | null;
  sections?: BasisSection[] | null;
  model_used?: string | null;
}

/**
 * Fold a stored basis-of-estimate document into the compact summary the copilot
 * renders. The document carries structured qualifications rather than free text,
 * so its notes become the narrative (when present) and the inclusion / exclusion
 * / assumption lists become labelled sections. Every field is treated as
 * optional so a sparse document never throws in the view.
 */
function mapBasisDocument(doc: EstimateBasisDocument, t: TFunction): BasisOfEstimateResult {
  const groups: { title: string; items: QualificationItem[] }[] = [
    {
      title: t('copilot.basis.inclusions', { defaultValue: 'Inclusions' }),
      items: doc.inclusions ?? [],
    },
    {
      title: t('copilot.basis.exclusions', { defaultValue: 'Exclusions' }),
      items: doc.exclusions ?? [],
    },
    {
      title: t('copilot.basis.assumptions', { defaultValue: 'Assumptions' }),
      items: doc.assumptions ?? [],
    },
  ];

  const sections: BasisSection[] = groups
    .map((group) => ({
      title: group.title,
      body: group.items
        .filter((item) => item.enabled !== false && Boolean(item.text))
        .map((item) => item.text)
        .join('\n'),
    }))
    .filter((section) => section.body.length > 0);

  const narrative = doc.notes && doc.notes.trim().length > 0 ? doc.notes : null;

  return { narrative, sections };
}

/** User-entered inputs for the conceptual (ROM) first-pass estimate. */
export interface ConceptualInputs {
  buildingType: string;
  /** Gross floor area as the raw input string; parsed to Decimal on the wire. */
  grossFloorArea: string;
  quality: string;
  region: string;
}

// ── View model ─────────────────────────────────────────────────────────────

/** Per-step view model the page maps over to render the stepper. */
export interface CopilotStepView {
  def: CopilotStepDef;
  phase: StepPhase;
  isRunning: boolean;
  error: Error | null;
  hasResult: boolean;
  /** Active (or a confirmed step being re-opened) and inputs are ready. */
  canRun: boolean;
  /** Active, inputs ready, and a fresh result is present. */
  canConfirm: boolean;
}

/** Everything `EstimateCopilotPage` needs to drive the guided flow. */
export interface CopilotFlow {
  inputsReady: boolean;
  confirmedCount: number;
  activeStepId: CopilotStepId | null;
  isComplete: boolean;
  progress: number;
  /** At-a-glance readiness: which steps are done and whether review-ready. */
  readiness: FlowReadiness;
  steps: CopilotStepView[];
  /** Reference lists (building types, quality levels, regions) for the ROM form. */
  reference: RomReference | undefined;
  /** Current conceptual-step inputs the user edits before running step 1. */
  conceptualInputs: ConceptualInputs;
  /** Patch one or more conceptual-step inputs. */
  setConceptualInput: (patch: Partial<ConceptualInputs>) => void;
  /** True once a building type and a positive gross floor area are entered. */
  conceptualReady: boolean;
  conceptual: ConceptualEstimateResult | undefined;
  scope: ScopeCoverageResult | undefined;
  audit: QualityAuditResult | undefined;
  basis: BasisOfEstimateResult | undefined;
  run: (id: CopilotStepId) => void;
  confirm: (id: CopilotStepId) => void;
  revisit: (id: CopilotStepId) => void;
  reset: () => void;
}

/** Inputs the flow operates on. Both come from the global project context. */
export interface CopilotFlowInput {
  projectId: string | null;
  boqId: string | null;
}

/**
 * The slice of a React Query mutation the flow actually drives. Declared
 * structurally so each strongly-typed `useMutation` result assigns to it
 * without a cast.
 */
interface StepMutation {
  mutate: () => void;
  reset: () => void;
  isPending: boolean;
  isSuccess: boolean;
  error: Error | null;
}

// ── Persistence (localStorage) ───────────────────────────────────────────────

/**
 * Read the persisted flow snapshot for a project, or `null` when nothing valid
 * is stored. Progress saved against a different BOQ is rejected so switching
 * BOQ within a project never restores the wrong estimate's state. Never throws
 * (missing storage, malformed JSON and stale shapes all fall back to `null`).
 */
function loadPersistedFlow(
  projectId: string | null,
  boqId: string | null,
): CopilotPersistedState | null {
  const key = copilotStorageKey(projectId);
  if (!key) return null;
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return null;
    const parsed = parsePersistedState(JSON.parse(raw));
    if (!parsed) return null;
    if (parsed.boqId !== null && boqId !== null && parsed.boqId !== boqId) return null;
    return parsed;
  } catch {
    return null;
  }
}

/** Stable signature of the persistable slice, to detect real changes cheaply. */
function flowSignature(confirmedCount: number, ranSteps: readonly CopilotStepId[]): string {
  return `${confirmedCount}|${ranSteps.join(',')}`;
}

/** Persist the flow snapshot for a project. Silently no-ops when unavailable. */
function savePersistedFlow(projectId: string | null, state: CopilotPersistedState): void {
  const key = copilotStorageKey(projectId);
  if (!key) return;
  try {
    localStorage.setItem(key, JSON.stringify(state));
  } catch {
    // Storage full or unavailable (private mode) - in-memory state still holds.
  }
}

/**
 * Build the guided estimate-copilot flow.
 *
 * @param input The active project and BOQ to run the flow against.
 * @returns A {@link CopilotFlow} the page renders and drives.
 */
export function useCopilotFlow({ projectId, boqId }: CopilotFlowInput): CopilotFlow {
  const { t, i18n } = useTranslation();

  // Restore any persisted progress for this project + BOQ once, on mount. The
  // panel is remounted per (project, BOQ) selection, so this initialiser
  // re-runs whenever the user picks a different estimate to work on.
  const [restored] = useState<CopilotPersistedState | null>(() =>
    loadPersistedFlow(projectId, boqId),
  );
  const [confirmedCount, setConfirmedCount] = useState(restored?.confirmedCount ?? 0);
  // Ids of steps that have produced a result. Seeded from the restored snapshot
  // (live mutation state is gone after a reload) and kept current below.
  const [ranSteps, setRanSteps] = useState<CopilotStepId[]>(restored?.ranSteps ?? []);

  const inputsReady = Boolean(projectId && boqId);

  // Conceptual (ROM) reference table — seeds the form's option lists and the
  // quality / region defaults. Cached for an hour; it is effectively static.
  const referenceQuery = useQuery({
    queryKey: ['rom-estimate', 'reference'],
    queryFn: romEstimateApi.reference,
    staleTime: 60 * 60 * 1000,
  });
  const reference = referenceQuery.data;

  // The four inputs the ROM calculator needs. Building type and area are entered
  // by the user; quality and region are seeded from the reference defaults once
  // it loads (while the user has not overridden them).
  const [conceptualInputs, setConceptualInputs] = useState<ConceptualInputs>({
    buildingType: '',
    grossFloorArea: '',
    quality: '',
    region: '',
  });

  const setConceptualInput = useCallback((patch: Partial<ConceptualInputs>) => {
    setConceptualInputs((prev) => ({ ...prev, ...patch }));
  }, []);

  useEffect(() => {
    if (!reference) return;
    setConceptualInputs((prev) => ({
      ...prev,
      quality: prev.quality || reference.default_quality || '',
      region: prev.region || reference.default_region || '',
    }));
  }, [reference]);

  // Step 1 may run only once a building type and a positive area are provided.
  const conceptualAreaNum = Number(conceptualInputs.grossFloorArea);
  const conceptualReady =
    Boolean(conceptualInputs.buildingType) &&
    Number.isFinite(conceptualAreaNum) &&
    conceptualAreaNum > 0;

  // Step 1 — conceptual first-pass number via the ROM calculator.
  const conceptualM = useMutation<ConceptualEstimateResult, Error, void>({
    mutationFn: () =>
      romEstimateApi.generate({
        building_type: conceptualInputs.buildingType,
        gross_floor_area: conceptualInputs.grossFloorArea,
        quality: conceptualInputs.quality || reference?.default_quality || 'standard',
        region: conceptualInputs.region || reference?.default_region || 'global',
        gfa_unit: 'm2',
      }),
  });

  // Step 2 — scope coverage.
  const scopeM = useMutation<ScopeCoverageResult, Error, void>({
    mutationFn: () =>
      apiPost<ScopeCoverageResult>(
        `/v1/boq/boqs/${encodeURIComponent(boqId ?? '')}/check-scope/`,
        { locale: i18n.language },
        { longRunning: true },
      ),
  });

  // Step 3 — quality audit.
  const auditM = useMutation<QualityAuditResult, Error, void>({
    mutationFn: () =>
      apiPost<QualityAuditResult>('/v1/validation/run/', {
        project_id: projectId,
        boq_id: boqId,
        rule_sets: [...DEFAULT_AUDIT_RULE_SETS],
      }),
  });

  // Step 4 — basis of estimate. The client posts to /v1/estimate-basis/generate
  // and returns the stored document, which we fold into the summary shape the
  // flow renders (a short narrative plus qualification sections).
  const basisM = useMutation<BasisOfEstimateResult, Error, void>({
    mutationFn: async () => {
      const doc = await generateBasis({ project_id: projectId ?? '', boq_id: boqId });
      return mapBasisDocument(doc, t);
    },
  });

  const mutations = useMemo(
    (): Record<CopilotStepId, StepMutation> => ({
      conceptual: conceptualM,
      scope: scopeM,
      audit: auditM,
      basis: basisM,
    }),
    [conceptualM, scopeM, auditM, basisM],
  );

  /** Reset every step's result at or after `fromIndex` (stale after a rollback). */
  const resetFrom = useCallback(
    (fromIndex: number) => {
      COPILOT_STEPS.forEach((s, i) => {
        if (i >= fromIndex) mutations[s.id].reset();
      });
      // Drop ran-flags for the rolled-back steps so readiness and the persisted
      // snapshot stop claiming a result the user has thrown away.
      setRanSteps((prev) => prev.filter((id) => indexOfStep(id) < fromIndex));
    },
    [mutations],
  );

  // Fold freshly produced results into the ran-set. This is what lets the
  // readiness summary and the persisted snapshot know which steps have output
  // (and, after a reload, is seeded from storage rather than live mutations).
  // Keyed on the success flags so it only fires when a result actually lands.
  useEffect(() => {
    const successById: Record<CopilotStepId, boolean> = {
      conceptual: conceptualM.isSuccess,
      scope: scopeM.isSuccess,
      audit: auditM.isSuccess,
      basis: basisM.isSuccess,
    };
    const live = COPILOT_STEPS.filter((s) => successById[s.id]).map((s) => s.id);
    if (live.length === 0) return;
    setRanSteps((prev) => {
      const merged = [...prev];
      let changed = false;
      for (const id of live) {
        if (!merged.includes(id)) {
          merged.push(id);
          changed = true;
        }
      }
      return changed ? merged : prev;
    });
  }, [conceptualM.isSuccess, scopeM.isSuccess, auditM.isSuccess, basisM.isSuccess]);

  // Persist progress whenever it changes, but never re-write the value we just
  // restored at mount. Guarding on a signature (rather than a "first run" flag)
  // also makes React StrictMode's dev remount a no-op, so merely opening the
  // copilot on another BOQ never clobbers a sibling BOQ's saved slot.
  const persistedSigRef = useRef(
    flowSignature(restored?.confirmedCount ?? 0, restored?.ranSteps ?? []),
  );
  useEffect(() => {
    const sig = flowSignature(confirmedCount, ranSteps);
    if (sig === persistedSigRef.current) return;
    persistedSigRef.current = sig;
    savePersistedFlow(projectId, { confirmedCount, ranSteps, boqId });
  }, [projectId, boqId, confirmedCount, ranSteps]);

  const run = useCallback(
    (id: CopilotStepId) => {
      if (!inputsReady) return;
      if (!canConfirmStep(id, confirmedCount)) return; // only the active step runs
      if (id === 'conceptual' && !conceptualReady) return; // ROM inputs required first
      mutations[id].mutate();
    },
    [inputsReady, confirmedCount, mutations, conceptualReady],
  );

  const confirm = useCallback(
    (id: CopilotStepId) => {
      if (!canConfirmStep(id, confirmedCount)) return;
      if (!mutations[id].isSuccess) return; // must have a fresh result to confirm
      setConfirmedCount((c) => confirmStepCount(c));
    },
    [confirmedCount, mutations],
  );

  const revisit = useCallback(
    (id: CopilotStepId) => {
      const next = revisitStep(id, confirmedCount);
      if (next === confirmedCount) return;
      setConfirmedCount(next);
      resetFrom(next);
    },
    [confirmedCount, resetFrom],
  );

  const reset = useCallback(() => {
    setConfirmedCount(0);
    resetFrom(0);
  }, [resetFrom]);

  const steps = useMemo<CopilotStepView[]>(
    () =>
      COPILOT_STEPS.map((def) => {
        const m = mutations[def.id];
        const phase = stepPhaseById(def.id, confirmedCount);
        const isActive = canConfirmStep(def.id, confirmedCount);
        const hasResult = m.isSuccess;
        // The conceptual step also needs its ROM inputs before it can run.
        const stepReady = def.id === 'conceptual' ? conceptualReady : true;
        return {
          def,
          phase,
          isRunning: m.isPending,
          error: m.error ?? null,
          hasResult,
          canRun: isActive && inputsReady && !m.isPending && stepReady,
          canConfirm: isActive && inputsReady && hasResult,
        };
      }),
    [mutations, confirmedCount, inputsReady, conceptualReady],
  );

  const readiness = useMemo<FlowReadiness>(
    () => deriveReadiness(confirmedCount, ranSteps),
    [confirmedCount, ranSteps],
  );

  return {
    inputsReady,
    confirmedCount,
    activeStepId: activeStepIdFor(confirmedCount),
    isComplete: isCompleteFor(confirmedCount),
    progress: progressPercent(confirmedCount),
    readiness,
    steps,
    reference,
    conceptualInputs,
    setConceptualInput,
    conceptualReady,
    conceptual: conceptualM.data,
    scope: scopeM.data,
    audit: auditM.data,
    basis: basisM.data,
    run,
    confirm,
    revisit,
    reset,
  };
}

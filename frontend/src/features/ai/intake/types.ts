// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// OpenConstructionERP — DataDrivenConstruction (DDC)
// AI Estimate Builder — conversational intake v2 (frontend types).
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// These mirror the backend Pydantic schemas in
// `backend/app/modules/ai_estimator/schemas.py` (IntakeState and friends).
// The intake endpoints live under `/api/v1/ai-estimator/`.

/** How the dialogue is driven: AI-phrased conversation vs the curated form. */
export type IntakeMode = 'ai' | 'offline';

/** The intake dialogue phases (see service._INTAKE_PHASES). */
export type IntakePhase =
  | 'collect_request'
  | 'extract'
  | 'clarify_round_1'
  | 'clarify_round_2'
  | 'clarify_round_3'
  | 'parameter_sheet'
  | 'compose_groups'
  | 'group_board'
  | 'done';

/** A composed package's grounding coverage from the live vector probe. */
export type CoverageBand = 'grounded' | 'weak' | 'gap';

/** The kind of control a question renders as. */
export type QuestionKind = 'number' | 'choice' | 'bool' | 'length';

export interface IntakeQuestionOption {
  value: string;
  /** i18n key (`aiest.choice.<value>`); the UI falls back to `value`. */
  label_key: string;
}

export interface IntakeQuestion {
  param_key: string;
  kind: QuestionKind;
  unit: string | null;
  required: boolean;
  options: IntakeQuestionOption[];
  /** Human question text (LLM-phrased on the AI path, curated offline). */
  prompt: string;
  /** The "unlocks" justification (i18n key) so the UI shows the payoff. */
  why: string;
  /** Prefilled when the value is already known from the free text. */
  current_value: unknown | null;
}

export interface ComposedPackage {
  package_key: string;
  trade: string;
  selected: boolean;
  stages: string[];
  group_ids: string[];
  /** The REAL live-probe result (never a placeholder). */
  coverage: CoverageBand;
  /** Real probe score or null. */
  best_score: number | null;
  quantity: number;
  unit: string;
  /** True when any quantity was derived from a proxy (estimated, editable). */
  estimated: boolean;
}

/** One advisory foreman-sequence warning (never blocking). */
export interface DependencyWarning {
  /** Always `aiest.dep.missing_prereq`. */
  code: string;
  successor: string;
  prerequisite: string;
  successor_stage: string;
  prerequisite_stage: string;
}

export interface TranscriptTurn {
  role: string;
  text?: string;
  [key: string]: unknown;
}

export interface IntakeState {
  run_id: string;
  mode: IntakeMode;
  phase: IntakePhase;
  round_idx: number;
  rounds_remaining: number;
  detected_type: string | null;
  /** Real type-detection confidence or null (null on the deterministic path). */
  type_confidence: number | null;
  params: Record<string, unknown>;
  /** The current round's question batch (empty when off-round). */
  questions: IntakeQuestion[];
  /** Populated from compose_groups onward. */
  packages: ComposedPackage[];
  /** Advisory foreman-sequence warnings for the selected package set. */
  dependency_warnings: DependencyWarning[];
  transcript: TranscriptTurn[];
  ai_connected: boolean;
  vector_ready: boolean;
  /** "no_ai_key" | "no_vectors" | "no_catalogue" | null. */
  degraded_reason: string | null;
  summary: string | null;
}

// ── Request bodies ───────────────────────────────────────────────────────────

export interface IntakeCreate {
  project_id: string;
  text?: string;
  name?: string | null;
  /** "ai" | "offline" | null — force a mode (tests / cost control). */
  mode_hint?: IntakeMode | null;
  /** Optional manual project-type pick when the user chose a tile. */
  project_type?: string | null;
  catalogue_id?: string | null;
  region?: string | null;
  currency?: string | null;
}

export interface IntakeAnswerRequest {
  answers: Record<string, unknown>;
  /** When true, compute the next phase; when false, just persist the answers. */
  advance: boolean;
  /** Optional change of the detected project type (re-seeds the questionnaire). */
  project_type?: string | null;
}

export interface ConfirmParametersRequest {
  params: Record<string, unknown>;
}

export interface WorkPackageSelection {
  package_key?: string | null;
  /** Free-text custom work the composer probes immediately. */
  custom_description?: string | null;
  unit?: string | null;
}

export interface IntakePackagesRequest {
  add?: WorkPackageSelection[];
  remove?: string[];
  /** {package_key: selected_bool}. */
  toggle?: Record<string, boolean>;
}

// ── Project-type registry (static, for the UI tiles + questionnaire) ──────────

export interface ProjectParamOut {
  key: string;
  kind: QuestionKind;
  unit: string | null;
  required: boolean;
  choices: string[];
  unlocks: string[];
  round_group: number;
  label_key: string;
  why_key: string;
}

export interface WorkPackageOut {
  key: string;
  trade: string;
  default_on: boolean;
  stages: string[];
  unit: string;
  label_key: string;
}

export interface ProjectTypeOut {
  key: string;
  label_key: string;
  synonyms: string[];
  params: ProjectParamOut[];
  packages: WorkPackageOut[];
  default_unit_system: string;
}

// ── Run read (the finish bridge returns a normal grouping-stage run) ──────────

export interface RunRead {
  id: string;
  project_id: string;
  status: string;
  current_stage: string;
  [key: string]: unknown;
}

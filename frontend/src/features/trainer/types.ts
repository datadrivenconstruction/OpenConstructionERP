// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Trainer (Academy) API types. Mirror of backend/app/modules/trainer/schemas.py:
// every interface below has a Pydantic model of the same name with the same
// fields, and every `const` array below lists exactly the values of the
// Python `Literal` it mirrors. backend/tests/unit/trainer/test_trainer_contract_parity.py
// reads this file and fails on any difference, so change both sides together.
//
// Conventions that come from the backend:
// - Money and every other decimal is a string ("30414.00"), never a number.
// - Nullable fields are always present, as null. Nothing is optional.
// - Nothing graded is ever sent: no answer values, no `correct` flags, no
//   unrevealed hints, no expected values.
//
// One property per line, `name: type;`, no trailing comment on that line: the
// parity test parses this file line by line.

// ── Vocabularies ────────────────────────────────────────────────────────────

export const TASK_STATUSES = ['not_started', 'in_progress', 'needs_revision', 'passed', 'locked'] as const;
export type TaskStatus = (typeof TASK_STATUSES)[number];

export const LOCK_STATES = ['open', 'locked'] as const;
export type LockState = (typeof LOCK_STATES)[number];

export const LOCK_KINDS = ['module', 'panel', 'tab', 'badge'] as const;
export type LockKind = (typeof LOCK_KINDS)[number];

export const RING_IDS = ['numbers', 'trace', 'explain'] as const;
export type RingId = (typeof RING_IDS)[number];

export const WEEK_DAY_STATES = ['done', 'off', 'empty'] as const;
export type WeekDayState = (typeof WEEK_DAY_STATES)[number];

export const OUTSIDE_COURSE_MODES = ['hidden', 'more'] as const;
export type OutsideCourse = (typeof OUTSIDE_COURSE_MODES)[number];

export const VALUE_KINDS = ['money', 'percent', 'number', 'date', 'text'] as const;
export type ValueKind = (typeof VALUE_KINDS)[number];

export const CHECK_KINDS = ['numbers', 'trace', 'explain'] as const;
export type CheckKind = (typeof CHECK_KINDS)[number];

export const ANSWER_KINDS = ['number', 'option', 'text'] as const;
export type AnswerKind = (typeof ANSWER_KINDS)[number];

export const ITEM_VERDICTS = ['ok', 'wrong', 'missing', 'error'] as const;
export type ItemVerdict = (typeof ITEM_VERDICTS)[number];

export const ITEM_SOURCES = ['panel', 'erp'] as const;
export type ItemSource = (typeof ITEM_SOURCES)[number];

export const ATTEMPT_VERDICTS = ['pass', 'fail'] as const;
export type AttemptVerdict = (typeof ATTEMPT_VERDICTS)[number];

export const DIAGNOSIS_KINDS = ['error', 'convention'] as const;
export type DiagnosisKind = (typeof DIAGNOSIS_KINDS)[number];

export const READBACK_STATES = ['match', 'mismatch', 'unknown'] as const;
export type ReadbackState = (typeof READBACK_STATES)[number];

export const ENROLMENT_STATUSES = ['queued', 'provisioning', 'active', 'completed', 'revoked', 'failed', 'suspended'] as const;
export type EnrolmentStatus = (typeof ENROLMENT_STATUSES)[number];

export const ENROLMENT_SOURCES = ['webhook', 'admin'] as const;
export type EnrolmentSource = (typeof ENROLMENT_SOURCES)[number];

// ── Public status: GET /v1/trainer/public/status/ ───────────────────────────

export interface PublicStatus {
  academy_mode: boolean;
  store_url: string | null;
}

// ── GET /v1/trainer/me ──────────────────────────────────────────────────────

export interface CourseBadge {
  id: string;
  title: string;
}

export interface CourseInfo {
  id: string;
  version: string;
  title: string;
  summary: string | null;
  language: string;
  country: string;
  locale: string;
  currency: string;
  contract: string | null;
  badge: CourseBadge | null;
}

export interface TaskTarget {
  route: string;
  anchor: string | null;
}

export interface TaskVideo {
  episode: string;
  title: string;
  route: string;
}

export interface TaskRings {
  numbers: boolean;
  trace: boolean;
  explain: boolean;
}

export interface TaskSummary {
  id: string;
  n: number;
  title: string;
  module: string;
  opens: string;
  opens_label: string;
  estimated_minutes: number | null;
  status: TaskStatus;
  rings: TaskRings;
  // Present for every task that is not locked.
  target: TaskTarget | null;
  video: TaskVideo | null;
  checked_prompt: string | null;
  lock_reason: string | null;
}

export interface UnlockTile {
  title: string;
  text: string;
}

export interface UnlockInfo {
  lock_id: string;
  kind: LockKind;
  state: LockState;
  opened_by_task: number;
  opened_at: string | null;
  seen: boolean;
  tiles: UnlockTile[];
}

export interface NavInfo {
  outside_course: OutsideCourse;
  always_open: string[];
}

export interface RingProgress {
  done: number;
  total: number;
}

export interface ProgressRings {
  numbers: RingProgress;
  trace: RingProgress;
  explain: RingProgress;
}

export interface CourseProgress {
  done: number;
  total: number;
  rings: ProgressRings;
}

export interface WeekDay {
  // YYYY-MM-DD
  date: string;
  state: WeekDayState;
}

export interface WeekInfo {
  goal: number;
  done: number;
  days: WeekDay[];
}

export interface TrainerMe {
  course: CourseInfo;
  tasks: TaskSummary[];
  unlocks: UnlockInfo[];
  nav: NavInfo;
  progress: CourseProgress;
  week: WeekInfo | null;
  level: string | null;
}

// ── GET /v1/trainer/tasks/{taskId} ──────────────────────────────────────────

export interface GivenItem {
  name: string;
  value: string;
  kind: ValueKind;
}

export interface CheckField {
  // The answer name to PUT.
  key: string;
  label: string;
  kind: ValueKind;
  currency: string | null;
}

export interface ChoiceOption {
  index: number;
  text: string;
}

export interface NumbersCheckView {
  id: string;
  kind: 'numbers';
  prompt: string;
  fields: CheckField[];
}

export interface ChoiceCheckView {
  // Also the answer name to PUT for this question.
  id: string;
  kind: 'trace' | 'explain';
  prompt: string;
  options: ChoiceOption[];
}

export type CheckView = NumbersCheckView | ChoiceCheckView;

export interface ReadbackItemView {
  id: string;
  what: string;
  kind: ValueKind;
}

export interface SavedAnswer {
  name: string;
  kind: AnswerKind;
  value_text: string | null;
  option_index: number | null;
}

export interface RelatedValue {
  // Ledger key of the figure: an identifier, never shown to the learner.
  name: string;
  value: string;
  kind: ValueKind;
  // Human name in the course language; null means the spec names it nowhere, so hide the row.
  label: string | null;
}

export interface Diagnosis {
  id: string;
  kind: DiagnosisKind;
  message: string;
  related: RelatedValue[];
}

export interface FieldResult {
  // Answer name for a panel item; answer name or readback id for an ERP item.
  key: string;
  source: ItemSource;
  verdict: ItemVerdict;
  observed: string | null;
  diagnosis: Diagnosis | null;
  feedback: string | null;
}

// POST /v1/trainer/tasks/{taskId}/check
export interface AttemptResult {
  attempt_id: string;
  client_attempt_id: string | null;
  task_id: string;
  verdict: AttemptVerdict;
  graded_items: number;
  passed_items: number;
  fields: FieldResult[];
  task_status: TaskStatus;
  rings: TaskRings;
  progress: CourseProgress;
  unlocked: string[];
  regressed: boolean;
  revealed_hint: string | null;
  checked_at: string;
}

export interface TaskView {
  id: string;
  n: number;
  title: string;
  module: string;
  status: TaskStatus;
  brief: string;
  given: GivenItem[];
  steps: string[];
  // Only the hints already revealed to this learner.
  hints: string[];
  hints_total: number;
  panel_notes: string[];
  has_date_steps: boolean;
  checks: CheckView[];
  readback: ReadbackItemView[];
  answers: SavedAnswer[];
  answers_revision: number;
  last_attempt: AttemptResult | null;
}

// ── PUT /v1/trainer/tasks/{taskId}/answers ──────────────────────────────────

export interface AnswerIn {
  name: string;
  value_text: string | null;
  option_index: number | null;
}

export interface AnswersPut {
  answers: AnswerIn[];
  revision: number;
}

export interface AnswersSaved {
  task_id: string;
  revision: number;
  answers: SavedAnswer[];
}

// ── POST /v1/trainer/tasks/{taskId}/check ───────────────────────────────────

export interface CheckRequest {
  client_attempt_id: string;
  revision: number | null;
}

// ── GET /v1/trainer/tasks/{taskId}/readback ─────────────────────────────────

export interface ReadbackValue {
  id: string;
  state: ReadbackState;
  app_value: string | null;
  kind: ValueKind;
  // i18n key telling the learner what to do about an `unknown` reading
  // (decision 40), e.g. `trainer.readback.open_leveling`; null otherwise.
  reason_key: string | null;
}

export interface ReadbackResponse {
  task_id: string;
  items: ReadbackValue[];
  read_at: string;
}

// ── POST /v1/trainer/tasks/{taskId}/hints/reveal ────────────────────────────

export interface RevealedHint {
  index: number;
  text: string;
}

// Decision 30: idempotent at the last hint.
export interface HintRevealResult {
  hint: RevealedHint;
  hints_revealed: number;
  hints_total: number;
}

// ── Admin: POST /v1/trainer/admin/enrolments/ ───────────────────────────────

export interface AdminEnrolmentCreate {
  email: string;
  full_name: string;
  course_key: string;
  locale: string | null;
}

export interface AdminEnrolmentOut {
  id: string;
  user_id: string;
  email: string;
  course_key: string;
  course_version: string;
  status: EnrolmentStatus;
  source: EnrolmentSource;
  project_id: string | null;
  current_task_n: number;
  created_at: string;
}

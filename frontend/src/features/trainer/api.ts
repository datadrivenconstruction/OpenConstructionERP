// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Typed fetch wrappers around the trainer (Academy) API.
//
// Every path lives in TRAINER_PATHS and is copied from the endpoint table in
// backend/app/modules/trainer/schemas.py. The app runs with
// `redirect_slashes=False`, so a trailing slash that differs from the router
// is a 404 and not a redirect: change a path here and in the router together.
//
//   GET  /v1/trainer/public/status/            -> PublicStatus
//   GET  /v1/trainer/me                        -> TrainerMe (404: no enrolment, returned as null)
//   GET  /v1/trainer/tasks/{taskId}            -> TaskView
//   PUT  /v1/trainer/tasks/{taskId}/answers    AnswersPut -> AnswersSaved (409: stale revision)
//   POST /v1/trainer/tasks/{taskId}/check      CheckRequest -> AttemptResult
//   GET  /v1/trainer/tasks/{taskId}/readback   -> ReadbackResponse
//   POST /v1/trainer/tasks/{taskId}/hints/reveal  -> 2xx (decision 15; the body is not read)
//   POST /v1/trainer/unlocks/{lockId}/seen     -> 204, idempotent
//
// The check body carries no answers. Typed numbers and chosen options both go
// through the answers PUT first; the check grades what is saved.

import { apiGet, apiPost, apiPut, ApiError } from '@/shared/lib/api';
import { uuid } from '@/shared/lib/browser';

import type {
  AnswerIn,
  AnswersPut,
  AnswersSaved,
  AttemptResult,
  CheckField,
  CheckRequest,
  ChoiceCheckView,
  PublicStatus,
  ReadbackResponse,
  TaskView,
  TrainerMe,
} from './types';

const seg = (value: string): string => encodeURIComponent(value);

export const TRAINER_PATHS = {
  publicStatus: '/v1/trainer/public/status/',
  me: '/v1/trainer/me',
  task: (taskId: string) => `/v1/trainer/tasks/${seg(taskId)}`,
  answers: (taskId: string) => `/v1/trainer/tasks/${seg(taskId)}/answers`,
  check: (taskId: string) => `/v1/trainer/tasks/${seg(taskId)}/check`,
  readback: (taskId: string) => `/v1/trainer/tasks/${seg(taskId)}/readback`,
  revealHint: (taskId: string) => `/v1/trainer/tasks/${seg(taskId)}/hints/reveal`,
  unlockSeen: (lockId: string) => `/v1/trainer/unlocks/${seg(lockId)}/seen`,
} as const;

/**
 * Thrown instead of sending a trainer write while the browser is offline.
 *
 * `api.ts` queues an offline write for replay and returns `undefined`. The
 * trainer must not take that path: a queued check hands the UI nothing to
 * show, and a queued answers PUT would replay later against a revision that
 * has moved on. So the answers PUT and the check refuse up front when
 * `navigator.onLine` is false, and `requireBody` refuses an empty answer as a
 * backstop for the case where the connection drops mid-call (that request may
 * already sit in the replay queue; the server's revision check and the
 * check's idempotency key make the replay harmless). The panel shows its own
 * "did not run" state.
 */
export class TrainerOfflineError extends Error {
  constructor(path: string) {
    super(`Trainer request was not sent (offline): ${path}`);
    this.name = 'TrainerOfflineError';
  }
}

function refuseOffline(path: string): void {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) throw new TrainerOfflineError(path);
}

function requireBody<T>(data: T | undefined, path: string): T {
  if (data === undefined || data === null) throw new TrainerOfflineError(path);
  return data;
}

/** The HTTP status of a failed trainer call, or null for a network failure. */
export function trainerErrorStatus(error: unknown): number | null {
  return error instanceof ApiError ? error.status : null;
}

/** A fresh idempotency key for one press of "Check". Safe on plain-http installs. */
export function newClientAttemptId(): string {
  return uuid();
}

/** Pre-login academy flag and store link. */
export function fetchPublicStatus(): Promise<PublicStatus> {
  return apiGet<PublicStatus>(TRAINER_PATHS.publicStatus);
}

/** The learner's active enrolment, or null when there is none (404). */
export async function fetchTrainerMe(): Promise<TrainerMe | null> {
  try {
    return await apiGet<TrainerMe>(TRAINER_PATHS.me);
  } catch (error) {
    if (trainerErrorStatus(error) === 404) return null;
    throw error;
  }
}

/** The redacted task view: no answer values, no unrevealed hints. */
export function fetchTrainerTask(taskId: string): Promise<TaskView> {
  return apiGet<TaskView>(TRAINER_PATHS.task(taskId));
}

/** What the ERP holds now for each readback item. Never the expected value. */
export function fetchTrainerReadback(taskId: string): Promise<ReadbackResponse> {
  return apiGet<ReadbackResponse>(TRAINER_PATHS.readback(taskId));
}

/** Save typed and chosen answers. 409 means `revision` is stale. */
export async function putTrainerAnswers(taskId: string, body: AnswersPut): Promise<AnswersSaved> {
  const path = TRAINER_PATHS.answers(taskId);
  refuseOffline(path);
  return requireBody(await apiPut<AnswersSaved | undefined, AnswersPut>(path, body), path);
}

/** Run the full check on what is saved. Idempotent on `client_attempt_id`. */
export async function postTrainerCheck(taskId: string, body: CheckRequest): Promise<AttemptResult> {
  const path = TRAINER_PATHS.check(taskId);
  refuseOffline(path);
  return requireBody(await apiPost<AttemptResult | undefined, CheckRequest>(path, body), path);
}

/** Reveal the next hint. Idempotent server-side; the task view then carries it. */
export async function postRevealHint(taskId: string): Promise<void> {
  await apiPost<unknown>(TRAINER_PATHS.revealHint(taskId));
}

/** Mark an unlock as celebrated. 204, idempotent. */
export async function postUnlockSeen(lockId: string): Promise<void> {
  await apiPost<void>(TRAINER_PATHS.unlockSeen(lockId));
}

// ── Answer builders ─────────────────────────────────────────────────────────

/**
 * The answer for one numbers field. `valueText` is the decimal string from
 * `parseCourseNumber`, or null to clear the field.
 */
export function numberAnswer(field: Pick<CheckField, 'key'>, valueText: string | null): AnswerIn {
  return { name: field.key, value_text: valueText, option_index: null };
}

/** The answer for a trace or explain question: its check id names it. */
export function optionAnswer(check: Pick<ChoiceCheckView, 'id'>, optionIndex: number | null): AnswerIn {
  return { name: check.id, value_text: null, option_index: optionIndex };
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// OpenConstructionERP — DataDrivenConstruction (DDC)
// AI Estimate Builder — conversational intake v2 (frontend API client).
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Thin typed wrappers over the intake endpoints mounted at
// `/api/v1/ai-estimator/`. Uses the shared apiGet/apiPost helpers (same
// pattern as `frontend/src/features/ai/api.ts`).

import { apiGet, apiPost } from '@/shared/lib/api';
import type {
  ConfirmParametersRequest,
  IntakeAnswerRequest,
  IntakeCreate,
  IntakePackagesRequest,
  IntakeState,
  ProjectTypeOut,
  RunRead,
} from './types';

const BASE = '/v1/ai-estimator';

export const intakeApi = {
  /**
   * Start a conversational intake from a free-text request.
   *
   * Creates a run in status `intake` plus an intake row, runs the extraction
   * step (AI or deterministic), and returns the first IntakeState. The
   * extraction can call an LLM, so this is a long-running request.
   */
  start: (body: IntakeCreate) =>
    apiPost<IntakeState, IntakeCreate>(`${BASE}/intake`, body, { longRunning: true }),

  /** Poll the intake state (while extraction / a round / compose runs). */
  get: (runId: string) => apiGet<IntakeState>(`${BASE}/runs/${runId}/intake`),

  /** Record the current round's answers and (optionally) advance the FSM. */
  answer: (runId: string, body: IntakeAnswerRequest) =>
    apiPost<IntakeState, IntakeAnswerRequest>(
      `${BASE}/runs/${runId}/intake/answer`,
      body,
      { longRunning: true },
    ),

  /** Confirm the parameter sheet (checkpoint A) and compose the group board. */
  confirmParameters: (runId: string, body: ConfirmParametersRequest) =>
    apiPost<IntakeState, ConfirmParametersRequest>(
      `${BASE}/runs/${runId}/intake/confirm-parameters`,
      body,
      { longRunning: true },
    ),

  /** Edit the package board: add / remove / toggle packages (re-probes). */
  editPackages: (runId: string, body: IntakePackagesRequest) =>
    apiPost<IntakeState, IntakePackagesRequest>(
      `${BASE}/runs/${runId}/intake/packages`,
      body,
      { longRunning: true },
    ),

  /** Confirm the group board (checkpoint B) and bridge to the run pipeline. */
  finish: (runId: string) => apiPost<RunRead>(`${BASE}/runs/${runId}/intake/finish`),

  /** The static project-type registry for the UI (tiles + questionnaire schema). */
  projectTypes: () => apiGet<ProjectTypeOut[]>(`${BASE}/project-types`),
};

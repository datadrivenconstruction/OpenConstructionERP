// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// OpenConstructionERP — DataDrivenConstruction (DDC)
// AI Estimate Builder — conversational intake v2 (state hook).
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Wires the intake FSM endpoints into a small stateful hook the panel
// consumes. The IntakeState returned by every mutation is the single source
// of truth; we hold it in local state and surface per-action pending/error.

import { useCallback, useState } from 'react';
import { intakeApi } from './api';
import type {
  ConfirmParametersRequest,
  IntakeAnswerRequest,
  IntakeCreate,
  IntakePackagesRequest,
  IntakeState,
  RunRead,
} from './types';

type IntakeAction =
  | 'start'
  | 'refresh'
  | 'answer'
  | 'confirm-parameters'
  | 'packages'
  | 'finish';

export interface UseIntakeResult {
  state: IntakeState | null;
  /** Which action is in flight (null when idle). */
  pending: IntakeAction | null;
  error: string | null;
  start: (body: IntakeCreate) => Promise<IntakeState | null>;
  refresh: () => Promise<IntakeState | null>;
  answer: (body: IntakeAnswerRequest) => Promise<IntakeState | null>;
  confirmParameters: (body: ConfirmParametersRequest) => Promise<IntakeState | null>;
  editPackages: (body: IntakePackagesRequest) => Promise<IntakeState | null>;
  finish: () => Promise<RunRead | null>;
  reset: () => void;
}

function messageOf(err: unknown): string {
  if (err instanceof Error) return err.message;
  return 'Something went wrong. Please try again.';
}

export function useIntake(): UseIntakeResult {
  const [state, setState] = useState<IntakeState | null>(null);
  const [pending, setPending] = useState<IntakeAction | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async <T,>(action: IntakeAction, fn: () => Promise<T>): Promise<T | null> => {
      setPending(action);
      setError(null);
      try {
        return await fn();
      } catch (err) {
        setError(messageOf(err));
        return null;
      } finally {
        setPending(null);
      }
    },
    [],
  );

  const start = useCallback(
    (body: IntakeCreate) =>
      run('start', async () => {
        const next = await intakeApi.start(body);
        setState(next);
        return next;
      }),
    [run],
  );

  const refresh = useCallback(
    () =>
      run('refresh', async () => {
        if (!state) return null;
        const next = await intakeApi.get(state.run_id);
        setState(next);
        return next;
      }),
    [run, state],
  );

  const answer = useCallback(
    (body: IntakeAnswerRequest) =>
      run('answer', async () => {
        if (!state) return null;
        const next = await intakeApi.answer(state.run_id, body);
        setState(next);
        return next;
      }),
    [run, state],
  );

  const confirmParameters = useCallback(
    (body: ConfirmParametersRequest) =>
      run('confirm-parameters', async () => {
        if (!state) return null;
        const next = await intakeApi.confirmParameters(state.run_id, body);
        setState(next);
        return next;
      }),
    [run, state],
  );

  const editPackages = useCallback(
    (body: IntakePackagesRequest) =>
      run('packages', async () => {
        if (!state) return null;
        const next = await intakeApi.editPackages(state.run_id, body);
        setState(next);
        return next;
      }),
    [run, state],
  );

  const finish = useCallback(
    () =>
      run('finish', async () => {
        if (!state) return null;
        return intakeApi.finish(state.run_id);
      }),
    [run, state],
  );

  const reset = useCallback(() => {
    setState(null);
    setPending(null);
    setError(null);
  }, []);

  return {
    state,
    pending,
    error,
    start,
    refresh,
    answer,
    confirmParameters,
    editPackages,
    finish,
    reset,
  };
}

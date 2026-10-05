// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// React Query hooks for the trainer (Academy).
//
// Every query is idle unless the box runs in academy mode AND there is a
// session, so on a normal install none of them ever fires. The flag here is
// the live one from `/api/system/status`; the cached first-paint flag lives in
// useTrainerMode.ts, which builds on this file (never the other way round).
//
// Mutations set no `mutationKey`: the global MutationCache in main.tsx
// invalidates `[mutationKey[0]]` after every success, which would refetch all
// trainer queries on every keystroke save. Each mutation invalidates exactly
// what it changed instead. They also opt out of the global error toast,
// because the task panel reports its own failures inline.
//
// The answer/check sequence: PUT the answers, then POST the check with the
// `revision` the PUT returned (AnswersSaved.revision). Do not read the revision
// back from the task cache between the two: the task query is invalidated by
// the PUT and may be mid-refetch.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { academyModeFrom, useSystemStatus } from '@/shared/hooks/useSystemStatus';
import { useAuthStore } from '@/stores/useAuthStore';

import {
  fetchPublicStatus,
  fetchTrainerMe,
  fetchTrainerReadback,
  fetchTrainerTask,
  postRevealHint,
  postTrainerCheck,
  postUnlockSeen,
  putTrainerAnswers,
  trainerErrorStatus,
} from './api';
import type {
  AnswersPut,
  AnswersSaved,
  AttemptResult,
  CheckRequest,
  PublicStatus,
  ReadbackResponse,
  TaskView,
  TrainerMe,
} from './types';

/**
 * Query keys. Literal arrays on purpose: the readback refetch filters the
 * cache by prefix, and other streams match `['trainer', ...]` directly.
 */
export const trainerKeys = {
  all: ['trainer'] as const,
  me: () => ['trainer', 'me'] as const,
  task: (taskId: string) => ['trainer', 'task', taskId] as const,
  readback: (taskId: string) => ['trainer', 'readback', taskId] as const,
  publicStatus: () => ['trainer', 'public-status'] as const,
};

const QUIET = { suppressGlobalErrorToast: true } as const;

/**
 * True when trainer queries may run: a session exists and the live system
 * status says `academy_mode: true`. False while the status is loading.
 */
export function useTrainerQueriesEnabled(): boolean {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const status = useSystemStatus();
  return isAuthenticated && academyModeFrom(status.data);
}

/**
 * The learner's enrolment. `data === null` means "no enrolment" (the 404),
 * which is a state and not an error; `isError` is reserved for real failures.
 */
export function useTrainerMe() {
  const enabled = useTrainerQueriesEnabled();
  return useQuery<TrainerMe | null>({
    queryKey: trainerKeys.me(),
    queryFn: fetchTrainerMe,
    enabled,
    staleTime: 60_000,
  });
}

/** The redacted view of one task. Idle without a task id. */
export function useTrainerTask(taskId: string | null | undefined) {
  const enabled = useTrainerQueriesEnabled() && !!taskId;
  return useQuery<TaskView>({
    queryKey: trainerKeys.task(taskId ?? ''),
    queryFn: () => fetchTrainerTask(taskId as string),
    enabled,
    staleTime: 30_000,
  });
}

/**
 * What the ERP shows now for the task's readback items.
 *
 * Always stale and refetched on window focus: the learner edits the project in
 * another part of the app and expects the panel to follow. Failures stay
 * quiet, because this refetches passively and the panel shows "unknown".
 */
export function useTrainerReadback(taskId: string | null | undefined) {
  const enabled = useTrainerQueriesEnabled() && !!taskId;
  return useQuery<ReadbackResponse>({
    queryKey: trainerKeys.readback(taskId ?? ''),
    queryFn: () => fetchTrainerReadback(taskId as string),
    enabled,
    staleTime: 0,
    refetchOnWindowFocus: true,
    meta: QUIET,
  });
}

/** Pre-login flag and store link, for the sign-in page. */
export function useTrainerPublicStatus(enabled = true) {
  return useQuery<PublicStatus>({
    queryKey: trainerKeys.publicStatus(),
    queryFn: fetchPublicStatus,
    enabled,
    retry: false,
    staleTime: Infinity,
    meta: QUIET,
  });
}

/**
 * Save the task's answers.
 *
 * On success the saved answers and the new revision go straight into the task
 * cache, then the task and `/me` are refetched because a changed answer can
 * move a passed task back to needs_revision. On 409 (stale revision) the task is refetched
 * so the next save carries the server's revision.
 */
export function useSaveTrainerAnswers(taskId: string) {
  const qc = useQueryClient();
  return useMutation<AnswersSaved, Error, AnswersPut>({
    mutationFn: (body) => putTrainerAnswers(taskId, body),
    meta: QUIET,
    onSuccess: (saved) => {
      qc.setQueryData<TaskView>(trainerKeys.task(taskId), (prev) =>
        prev ? { ...prev, answers: saved.answers, answers_revision: saved.revision } : prev,
      );
      // Status and last_attempt move server-side when an answer changes.
      void qc.invalidateQueries({ queryKey: trainerKeys.task(taskId) });
      void qc.invalidateQueries({ queryKey: trainerKeys.me() });
    },
    onError: (error) => {
      if (trainerErrorStatus(error) === 409) {
        void qc.invalidateQueries({ queryKey: trainerKeys.task(taskId) });
      }
    },
  });
}

/**
 * Run the check. Build the body with `newClientAttemptId()` once per press and
 * reuse it on a retry of the same press, so a double submit is one attempt.
 *
 * On success the attempt lands in the task cache as `last_attempt`, then `/me`
 * (status, rings, unlocks), the task and the readback are refetched. On 409
 * (task locked, or a stale revision) `/me` and the task are refetched, so the
 * panel can show why and the next press carries the current revision.
 */
export function useCheckTrainerTask(taskId: string) {
  const qc = useQueryClient();
  return useMutation<AttemptResult, Error, CheckRequest>({
    mutationFn: (body) => postTrainerCheck(taskId, body),
    meta: QUIET,
    onSuccess: (result) => {
      qc.setQueryData<TaskView>(trainerKeys.task(taskId), (prev) =>
        prev ? { ...prev, status: result.task_status, last_attempt: result } : prev,
      );
      void qc.invalidateQueries({ queryKey: trainerKeys.me() });
      void qc.invalidateQueries({ queryKey: trainerKeys.task(taskId) });
      void qc.invalidateQueries({ queryKey: trainerKeys.readback(taskId) });
    },
    onError: (error) => {
      if (trainerErrorStatus(error) === 409) {
        void qc.invalidateQueries({ queryKey: trainerKeys.me() });
        void qc.invalidateQueries({ queryKey: trainerKeys.task(taskId) });
      }
    },
  });
}

/** Reveal the next hint; the refetched task view carries it. */
export function useRevealTrainerHint(taskId: string) {
  const qc = useQueryClient();
  return useMutation<void, Error, void>({
    mutationFn: () => postRevealHint(taskId),
    meta: QUIET,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: trainerKeys.task(taskId) });
    },
  });
}

/**
 * Mark an unlock as seen. The `/me` cache flips `seen` at once, so the unlock
 * host does not show the same celebration twice while the POST is in flight.
 * A failed POST restores nothing: the host keeps the id in the UI store's
 * `celebrated` list and retries on the next `/me` load.
 */
export function useMarkUnlockSeen() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (lockId) => postUnlockSeen(lockId),
    meta: QUIET,
    onMutate: (lockId) => {
      qc.setQueryData<TrainerMe | null>(trainerKeys.me(), (prev) =>
        prev
          ? { ...prev, unlocks: prev.unlocks.map((u) => (u.lock_id === lockId ? { ...u, seen: true } : u)) }
          : prev,
      );
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: trainerKeys.me() });
    },
  });
}

/** Drop every trainer query, e.g. when the signed-in user changes. */
export function removeTrainerQueries(qc: ReturnType<typeof useQueryClient>): void {
  qc.removeQueries({ queryKey: trainerKeys.all });
}

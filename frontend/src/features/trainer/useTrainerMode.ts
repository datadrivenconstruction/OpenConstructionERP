// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Is this user inside an Academy course right now?
//
// Two inputs: the box flag (`academy_mode` from `/api/system/status`) and the
// learner's enrolment (`/v1/trainer/me`, 404 = none). The result is one
// discriminated state so every consumer handles the same six cases:
//
//   off       signed out, the box is not an academy box, or the status failed (fail open:
//             locks are navigation only and every API stays open)
//   checking  the status has not answered yet, but the cached flag from the
//             last visit says academy; render a placeholder, not the module
//   loading   academy box, `/me` in flight
//   none      academy box, no enrolment: nothing is locked
//   error     academy box, `/me` failed: gated routes show the error state
//   enrolled  academy box with an active enrolment: `me` is set
//
// The flag is mirrored into localStorage so the first paint of a returning
// learner does not flash the full menu. On a normal install the mirror only
// ever removes a key that is not there.
//
// This hook never changes the UI language (founder Q5) and never writes the
// user's view mode (decision 3).

import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { academyModeFrom, useSystemStatus } from '@/shared/hooks/useSystemStatus';
import { useAuthStore } from '@/stores/useAuthStore';

import { trainerKeys, useTrainerMe } from './queries';
import type { TrainerMe } from './types';
import { useTrainerUiStore } from './useTrainerUiStore';

export const TRAINER_MODE_STORAGE_KEY = 'oe_trainer_mode';

export type TrainerModeState = 'off' | 'checking' | 'loading' | 'none' | 'error' | 'enrolled';

export interface TrainerMode {
  state: TrainerModeState;
  /** The box is an academy box: the live flag, or the cached one while the status loads. */
  academyMode: boolean;
  /** The live status has answered (or failed), so `academyMode` is no longer a guess. */
  known: boolean;
  /** `state === 'enrolled'`: the course shapes the menu and the locks apply. */
  active: boolean;
  /** The enrolment, only when `state === 'enrolled'`. */
  me: TrainerMe | null;
  /** Refetch `/me` (the Retry and "Check again" buttons). */
  refetch: () => void;
}

/** The flag the last visit saw. False when storage is empty or unavailable. */
export function readCachedAcademyFlag(): boolean {
  try {
    return localStorage.getItem(TRAINER_MODE_STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

/** Store the flag; `false` removes the key, so a normal install keeps none. */
export function writeCachedAcademyFlag(on: boolean): void {
  try {
    if (on) localStorage.setItem(TRAINER_MODE_STORAGE_KEY, '1');
    else localStorage.removeItem(TRAINER_MODE_STORAGE_KEY);
  } catch {
    /* storage unavailable: the next first paint just has no cached flag */
  }
}

/**
 * Pure state machine behind `useTrainerMode`, exported for tests and for
 * callers that already hold the inputs.
 */
export function resolveTrainerMode(input: {
  signedIn: boolean;
  statusSettled: boolean;
  statusFlag: boolean;
  cachedFlag: boolean;
  meStatus: 'pending' | 'error' | 'success';
  me: TrainerMe | null | undefined;
}): Pick<TrainerMode, 'state' | 'academyMode' | 'known'> {
  // Signed out: the status endpoint is signed-in only, so it will never
  // settle; a flag cached by an earlier learner must not leave this waiting.
  if (!input.signedIn) return { state: 'off', academyMode: false, known: true };
  if (!input.statusSettled) {
    return input.cachedFlag
      ? { state: 'checking', academyMode: true, known: false }
      : { state: 'off', academyMode: false, known: false };
  }
  if (!input.statusFlag) return { state: 'off', academyMode: false, known: true };
  const base = { academyMode: true, known: true } as const;
  if (input.meStatus === 'pending') return { ...base, state: 'loading' };
  // An error with older data in the cache keeps the course on screen; the
  // background refetch failing does not take the menu away mid-task.
  if (input.meStatus === 'error' && input.me === undefined) return { ...base, state: 'error' };
  // A "Check again" refetch after a 404 keeps showing "none" until it answers.
  if (input.me === null || input.me === undefined) return { ...base, state: 'none' };
  return { ...base, state: 'enrolled' };
}

// The user the trainer cache and the UI store belong to. Module scope, because the hook is
// mounted in many places and only the first to see a new user should reset.
let trainerCacheOwner: string | null | undefined;

/** Test hook: forget which user the trainer cache belongs to. */
export function __resetTrainerCacheOwnerForTests(): void {
  trainerCacheOwner = undefined;
}

export function useTrainerMode(): TrainerMode {
  const qc = useQueryClient();
  const userId = useAuthStore((s) => s.userId);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const status = useSystemStatus();
  const meQuery = useTrainerMe();

  // Without a session there is nothing to settle: the status query is idle.
  const statusSettled = isAuthenticated && (status.isSuccess || status.isError);
  const statusFlag = academyModeFrom(status.data);

  const resolved = resolveTrainerMode({
    signedIn: isAuthenticated,
    statusSettled,
    statusFlag,
    cachedFlag: readCachedAcademyFlag(),
    meStatus: meQuery.status,
    me: meQuery.data,
  });

  // Mirror only a settled answer. A failed status reads as off for this
  // session but does not wipe the cache: one blip should not flash the menu
  // on the next visit.
  useEffect(() => {
    if (status.isSuccess) writeCachedAcademyFlag(statusFlag);
  }, [status.isSuccess, statusFlag]);

  // A different user in the same tab (or a sign-out) must never see the
  // previous user's course, drafts or celebrations. Reset (not remove) so
  // mounted observers refetch for the new user.
  useEffect(() => {
    if (trainerCacheOwner === undefined) {
      trainerCacheOwner = userId;
      return;
    }
    if (trainerCacheOwner !== userId) {
      trainerCacheOwner = userId;
      useTrainerUiStore.getState().reset();
      void qc.resetQueries({ queryKey: trainerKeys.all });
    }
  }, [qc, userId]);

  const me = resolved.state === 'enrolled' ? (meQuery.data ?? null) : null;
  const refetchMe = meQuery.refetch;
  return {
    ...resolved,
    active: resolved.state === 'enrolled',
    me,
    refetch: () => {
      void refetchMe();
    },
  };
}

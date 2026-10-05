// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The route gate for the Academy, used once in App.tsx's `P` wrapper:
//
//   const trainerLock = useTrainerRouteLock();
//   if (trainerLock) return <TrainerRouteOutcome outcome={trainerLock} />;
//
// Locks are UI only (founder decision): a closed lock swaps the page for
// `LockedModulePage` and never blocks a request. Module APIs stay open, so
// failing open loses nothing. The page title is still set by `P`, so a locked
// /variations keeps the "Variations" title.
//
// Outcomes (frontend design §3, failure modes):
//   trainer off, no enrolment, open route  -> null (the page renders as today)
//   status or `/me` still loading          -> pending, but only on a route a
//                                             registered lock covers
//   `/me` failed                           -> error, same routes
//   lock closed for this route             -> locked
//   `/dashboard` while enrolled            -> redirect to the course map

import { lazy, Suspense, useMemo } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';

import { COURSE_MAP_ROUTE, closedLockForPath, lockIdsForPath, normalizePath } from './routeMatch';
import { useTrainerMode } from './useTrainerMode';

/**
 * The landing routes a learner is sent away from, to the course map. Matched
 * exactly: a project's own dashboard under `/projects/:id/...` stays.
 */
const LEARNER_LANDING_REDIRECTS: readonly string[] = ['/dashboard'];

export type TrainerRouteLock =
  | { kind: 'pending' }
  | { kind: 'locked'; lockId: string }
  | { kind: 'error' }
  | { kind: 'redirect'; to: string };

function isLearnerLanding(pathname: string): boolean {
  return LEARNER_LANDING_REDIRECTS.includes(normalizePath(pathname));
}

/**
 * What the current route should show under the Academy, or null to render
 * the page unchanged. Always null when the trainer is off.
 */
export function useTrainerRouteLock(): TrainerRouteLock | null {
  const { pathname } = useLocation();
  const mode = useTrainerMode();

  let kind: TrainerRouteLock['kind'] | null = null;
  let lockId: string | null = null;
  switch (mode.state) {
    case 'off':
    case 'none':
      break;
    case 'checking':
    case 'loading':
      if (isLearnerLanding(pathname) || lockIdsForPath(pathname).length > 0) kind = 'pending';
      break;
    case 'error':
      if (lockIdsForPath(pathname).length > 0) kind = 'error';
      break;
    case 'enrolled':
      if (isLearnerLanding(pathname)) {
        kind = 'redirect';
      } else {
        lockId = closedLockForPath(pathname, mode.me);
        if (lockId) kind = 'locked';
      }
      break;
  }

  // One object per outcome, so `P` does not see a new value on every render.
  return useMemo<TrainerRouteLock | null>(() => {
    switch (kind) {
      case 'pending':
        return { kind: 'pending' };
      case 'error':
        return { kind: 'error' };
      case 'redirect':
        return { kind: 'redirect', to: COURSE_MAP_ROUTE };
      case 'locked':
        return lockId ? { kind: 'locked', lockId } : null;
      default:
        return null;
    }
  }, [kind, lockId]);
}

const LockedModulePage = lazy(() => import('./LockedModulePage').then((m) => ({ default: m.LockedModulePage })));

/** Inline spinner shown while the course decides whether a route is open. */
export function TrainerRoutePending() {
  const { t } = useTranslation();
  return (
    <div role="status" aria-live="polite" className="flex min-h-[40vh] items-center justify-center">
      <Loader2 size={24} className="animate-spin text-content-tertiary motion-reduce:animate-none" aria-hidden="true" />
      <span className="sr-only">{t('trainer.state.loading', { defaultValue: 'Loading your course' })}</span>
    </div>
  );
}

export interface TrainerRouteOutcomeProps {
  outcome: TrainerRouteLock;
}

/**
 * Renders a non-null `useTrainerRouteLock()` result in place of the page.
 *
 * It reads the trainer state once here and hands it to the locked page, which
 * mounts and unmounts as the state moves between loading and error. This
 * component stays mounted across that move, so it never adds a `/me` observer
 * in the error state (see `TrainerLockMode` for the loop that would cause).
 */
export function TrainerRouteOutcome({ outcome }: TrainerRouteOutcomeProps) {
  const mode = useTrainerMode();
  switch (outcome.kind) {
    case 'pending':
      return <TrainerRoutePending />;
    case 'redirect':
      return <Navigate to={outcome.to} replace />;
    case 'locked':
    case 'error':
      return (
        <Suspense fallback={<TrainerRoutePending />}>
          <LockedModulePage lockId={outcome.kind === 'locked' ? outcome.lockId : null} mode={mode} />
        </Suspense>
      );
  }
}

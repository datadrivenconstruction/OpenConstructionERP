// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Mounted once in the app shell, always, and not keyed by the route, so what
// it hosts survives navigation (the ModuleVideosSlot pattern).
//
// It calls `useTrainerMode()` on every render whatever the state: that hook
// owns the reset when the signed-in user changes (decision 33), and the slot
// is the one observer that is always there to see the change.
//
// Trainer off, checking, loading, error or no enrolment: renders null and
// loads nothing. Enrolled: lazily loads the task dock (it hides itself when
// there is no current task and on the course map) and the unlock host.

import { lazy, Suspense } from 'react';

import { useTrainerMode } from './useTrainerMode';

const TaskDock = lazy(() => import('./TaskDock').then((m) => ({ default: m.TaskDock })));
const UnlockHost = lazy(() => import('./UnlockHost').then((m) => ({ default: m.UnlockHost })));

export function TrainerSlot() {
  const mode = useTrainerMode();
  if (!mode.active || !mode.me) return null;
  return (
    <Suspense fallback={null}>
      <TaskDock />
      <UnlockHost me={mode.me} />
    </Suspense>
  );
}

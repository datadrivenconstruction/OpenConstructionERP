// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Hides its children from a learner. Used around things that would pull a
// learner out of the course, such as the product tour (it spotlights menu
// groups the course hides and reveals Advanced mode).
//
// Hidden while the box is an academy box and the learner may be enrolled:
// the cached flag says academy and the status is still loading, `/me` is
// loading or failed, or there is an enrolment. Shown when the trainer is off
// and when an academy box has no enrolment for this user (an admin, say).
// With the trainer off it renders the children unchanged, in a fragment.

import type { ReactNode } from 'react';

import { useTrainerMode } from './useTrainerMode';

export interface TrainerHidesProps {
  children: ReactNode;
}

export function TrainerHides({ children }: TrainerHidesProps) {
  const { state } = useTrainerMode();
  if (state === 'off' || state === 'none') return <>{children}</>;
  return null;
}

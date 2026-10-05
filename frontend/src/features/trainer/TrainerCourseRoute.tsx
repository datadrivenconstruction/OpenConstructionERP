// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The `/academy` route switch. On an academy box it renders the course map;
// everywhere else it renders exactly what an unknown URL renders today, so a
// normal install cannot tell the route exists.
//
// While the system status is still loading, the flag cached by the last visit
// decides (a returning learner gets the map without a flash of "Not Found");
// with no cached flag it renders `off`. The course map itself handles loading,
// error and "no course yet" once it is on.
//
// Both branches are render functions, so the branch not taken is never built
// (the lazy course map chunk is not fetched on a normal install).

import type { ReactNode } from 'react';

import { useTrainerMode } from './useTrainerMode';

export interface TrainerCourseRouteProps {
  /** The course map, wrapped as the route table wraps every page. */
  on: () => ReactNode;
  /** What the catch-all route renders. */
  off: () => ReactNode;
}

export function TrainerCourseRoute({ on, off }: TrainerCourseRouteProps) {
  const { academyMode } = useTrainerMode();
  return <>{academyMode ? on() : off()}</>;
}

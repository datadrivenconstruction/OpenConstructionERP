// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { Navigate, useLocation } from 'react-router-dom';

import { safeNextPath } from './nextPath';

/**
 * Redirect target for an already-authenticated visitor who lands on an auth
 * route (`/login`, `/login-next`, `/register`, `/forgot-password`).
 *
 * Honours a `?next=` deep link - e.g. a case study links to
 * `/schedule`, RequireAuth bounces the signed-out visitor to
 * `/login?next=/schedule`, and once they hold a session we send them straight
 * to `/schedule` instead of a blanket bounce to the dashboard. Uses the same
 * `safeNextPath` as the login form so a redirect race between the two cannot
 * drop the `next`. With no (or an unsafe) `next` it resolves to `/`, which the
 * app forwards to the dashboard - the previous behaviour.
 */
export function AuthedHome() {
  const { search } = useLocation();
  return <Navigate to={safeNextPath(search)} replace />;
}

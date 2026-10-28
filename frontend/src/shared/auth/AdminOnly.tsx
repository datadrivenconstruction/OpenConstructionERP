// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';

interface AdminOnlyProps {
  children: ReactNode;
  /** Where to redirect non-admin users. Defaults to /404 so the route
   *  is indistinguishable from a non-existent path (the existence of
   *  dev-only surfaces is itself a soft leak we don't want to advertise
   *  in production). */
  redirectTo?: string;
}

/**
 * Route gate that only renders its children for users with the `admin`
 * role on their JWT. Non-admin users (including unauthenticated ones,
 * since RequireAuth already runs upstream of every protected route in
 * App.tsx) are redirected to /404 by default — the surface is hidden
 * rather than visibly forbidden so we don't advertise the existence of
 * developer / internal tools.
 *
 * This is a UX guard only — backend permission checks remain the real
 * authority on any data the page might read. The client gate just
 * keeps dev-only routes (Styles Lab, EAC demos, Architecture Map) out
 * of a regular customer's day-to-day surface area.
 */
export function AdminOnly({ children, redirectTo = '/404' }: AdminOnlyProps) {
  const userRole = useAuthStore((s) => s.userRole);
  if (userRole !== 'admin') {
    return <Navigate to={redirectTo} replace />;
  }
  return <>{children}</>;
}

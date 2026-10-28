// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Project setup-profile hooks + phase-grouping model.
 *
 * Slice 3 reorganises the sidebar into NUMBERED execution-phase groups
 * with a vertical "route line". This file owns:
 *
 *  • `PHASE_GROUPS` — the 4 execution phases (Estimation → Planning →
 *    Execution → Quality & Closure), each an ordered list of sidebar
 *    routes. Refined from the existing functional nav groups.
 *  • `ROUTE_TO_MODULE` — sidebar route → backend `ProjectModule.module_name`
 *    so the sidebar can read per-project `enabled`/`ordinal` and grey
 *    off-scope items.
 *  • `useActiveProjectProfile()` — fetches the active project's
 *    profile + module assignments. Degrades to `null` (today's flat
 *    behaviour) when there is no active project, no profile, or focus
 *    mode is off.
 *
 * Presentation-only: this NEVER unloads a module or blocks a route —
 * it only drives the sidebar's visual emphasis.
 */

import { useQuery } from '@tanstack/react-query';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { projectsApi, type ProjectProfileResult } from './api';

/** One numbered execution phase shown as a stepper rail in the sidebar. */
export interface PhaseGroup {
  /** Stable id used for collapse persistence + keys. */
  id: string;
  /** i18n key for the phase label. */
  labelKey: string;
  /** English default (inline-t fallback). */
  labelEn: string;
  /** Ordered sidebar `to` routes that belong to this phase. */
  routes: string[];
}

/**
 * The 4 numbered execution phases. Order = the badge number (1..4).
 * Routes are listed in their natural in-phase order; per-project the
 * sidebar re-sorts by `ProjectModule.ordinal` when a profile exists.
 *
 * These are a curated subset of the existing functional nav groups —
 * the global flat nav (Overview, Communication, Regional, bottom nav,
 * dynamic module items) still renders unchanged outside focus mode and
 * is appended after the phases inside focus mode so nothing disappears.
 */
export const PHASE_GROUPS: PhaseGroup[] = [
  {
    id: 'phase_estimation',
    labelKey: 'nav.phase_estimation',
    labelEn: 'Estimation',
    routes: [
      '/boq',
      '/costs',
      '/match-elements',
      '/assemblies',
      '/catalog',
      '/takeoff?tab=measurements',
      '/dwg-takeoff',
      '/data-explorer',
      '/bim',
      '/ai-estimate',
    ],
  },
  {
    id: 'phase_planning',
    labelKey: 'nav.phase_planning',
    labelEn: 'Planning',
    routes: [
      '/schedule',
      '/schedule-advanced',
      '/tasks',
      '/5d',
      '/cost-control',
      '/risks',
    ],
  },
  {
    id: 'phase_execution',
    labelKey: 'nav.phase_execution',
    labelEn: 'Execution',
    routes: [
      '/daily-diary',
      '/field-reports',
      '/finance',
      '/procurement',
      '/changeorders',
      '/subcontractors',
      '/equipment',
      '/resources',
      '/service',
    ],
  },
  {
    id: 'phase_closure',
    labelKey: 'nav.phase_closure',
    labelEn: 'Quality & Closure',
    routes: [
      '/validation',
      '/inspections',
      '/ncr',
      '/safety',
      '/punchlist',
      '/qms',
      '/hse-advanced',
      '/reports',
      '/cde',
    ],
  },
];

/**
 * Sidebar route → backend module folder id (`ProjectModule.module_name`).
 *
 * Only routes that map to a real per-project module need an entry; a
 * route absent from this map is treated as "always active" (never
 * greyed) so global/infrastructure nav is never suppressed.
 */
export const ROUTE_TO_MODULE: Record<string, string> = {
  '/boq': 'boq',
  '/costs': 'costs',
  '/match-elements': 'match_elements',
  '/assemblies': 'assemblies',
  '/catalog': 'catalog',
  '/takeoff?tab=measurements': 'takeoff',
  '/dwg-takeoff': 'dwg_takeoff',
  '/data-explorer': 'bim_hub',
  '/bim': 'bim_hub',
  '/ai-estimate': 'ai',
  '/schedule': 'schedule',
  '/schedule-advanced': 'schedule_advanced',
  '/tasks': 'tasks',
  '/5d': 'costmodel',
  '/cost-control': 'costmodel',
  '/risks': 'risk',
  '/daily-diary': 'daily_diary',
  '/field-reports': 'fieldreports',
  '/finance': 'finance',
  '/procurement': 'procurement',
  '/changeorders': 'changeorders',
  '/subcontractors': 'subcontractors',
  '/equipment': 'equipment',
  '/resources': 'resources',
  '/service': 'service',
  '/validation': 'validation',
  '/inspections': 'inspections',
  '/ncr': 'ncr',
  '/safety': 'safety',
  '/punchlist': 'punchlist',
  '/qms': 'qms',
  '/hse-advanced': 'hse_advanced',
  '/reports': 'reporting',
  '/cde': 'cde',
};

/**
 * App-shell routes that are NEVER project-scoped: they must always be
 * reachable and never numbered or greyed, even when their slug happens
 * to collide with a profile `module_name` (e.g. `projects`, `users`).
 */
export const NEVER_GATE_ROUTES: ReadonlySet<string> = new Set([
  '/',
  '/projects',
  '/files',
  '/users',
  '/modules',
  '/settings',
  '/about',
  '/project-intelligence', // PI is always-on core — never suppress.
]);

/** Fast lookup: every route that lives in some phase group. */
export const PHASED_ROUTES: ReadonlySet<string> = new Set(
  PHASE_GROUPS.flatMap((g) => g.routes),
);

/**
 * Active project's setup profile + resolved module assignments.
 *
 * Returns `data: undefined` until loaded and never throws to the
 * caller (a 404 = "no profile yet" is a valid degraded state, handled
 * by the sidebar by falling back to the flat layout).
 */
export function useActiveProjectProfile(): {
  projectId: string | null;
  profile: ProjectProfileResult | undefined;
  isLoading: boolean;
} {
  const projectId = useProjectContextStore((s) => s.activeProjectId);

  const { data, isLoading } = useQuery<ProjectProfileResult | null>({
    queryKey: ['project-profile', projectId],
    queryFn: async () => {
      if (!projectId) return null;
      try {
        return await projectsApi.getProfile(projectId);
      } catch {
        // 404 (no profile yet) or any transient error → degrade to the
        // flat sidebar rather than surface an error in the chrome.
        return null;
      }
    },
    enabled: !!projectId,
    staleTime: 60_000,
    retry: false,
  });

  return {
    projectId: projectId ?? null,
    profile: data ?? undefined,
    isLoading: !!projectId && isLoading,
  };
}

/**
 * Per-project module lookup for the sidebar.
 *
 * `byRoute(route)` → `{ enabled, ordinal }` or `null` when the profile
 * doesn't constrain that route (no profile / focus mode off / route
 * not module-backed). The sidebar greys an item only when this returns
 * `enabled === false`.
 */
export interface ModuleGate {
  enabled: boolean;
  ordinal: number | null;
}

export function buildModuleGate(
  profile: ProjectProfileResult | undefined,
): {
  active: boolean;
  byRoute: (route: string) => ModuleGate | null;
} {
  // Focus mode off, or no profile → flat behaviour (sidebar ignores us).
  const active = !!profile && profile.profile.focus_mode_enabled === true;
  if (!active || !profile) {
    return { active: false, byRoute: () => null };
  }
  const byName = new Map(profile.modules.map((m) => [m.module_name, m]));
  return {
    active: true,
    byRoute: (route: string) => {
      // App-shell routes are never project-scoped.
      if (NEVER_GATE_ROUTES.has(route)) return null;
      const base = route.split('?')[0] ?? route;
      // Resolve the backing module: explicit overrides first (for the
      // routes whose slug ≠ module folder, e.g. /5d → costmodel), then
      // fall back to the route slug with hyphens normalised to the
      // underscore convention used by `ProjectModule.module_name`
      // (e.g. /bid-management → bid_management). No per-module list to
      // maintain — any module-backed route is gated automatically.
      const moduleName =
        ROUTE_TO_MODULE[route] ??
        ROUTE_TO_MODULE[base] ??
        base.replace(/^\//, '').replace(/-/g, '_');
      if (!moduleName) return null;
      const row = byName.get(moduleName);
      if (!row) return null; // route not a profile module → neutral
      return { enabled: row.enabled, ordinal: row.ordinal ?? null };
    },
  };
}

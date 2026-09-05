// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Module-presence hook — drives sidebar dimming.
 *
 * Backend endpoint: GET /api/v1/projects/{project_id}/module-presence
 * returns a flat object of bool fields, one per sidebar module slug
 * (e.g. boq, takeoff, clash, smart_views, ...). True = the module has
 * at least one row for this project; False = empty.
 *
 * Cached per project for 60 s server-side AND 60 s here. The sidebar
 * applies a 3-state visual gradient using the returned booleans:
 *   • empty   → opacity-55 + text-zinc-500
 *   • normal  → default styling
 *   • hot     → 4 px primary dot (not driven by this hook — future)
 *
 * When no project is active the hook returns an empty record so every
 * sidebar item renders at "normal" weight (i.e. no dimming applied).
 * A genuine "all empty" project still returns a populated record with
 * all-false flags, which is what produces the dimming.
 */

import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

/** Wire-format from `GET /v1/projects/{id}/module-presence`. */
export type ModulePresenceMap = Record<string, boolean>;

/** Slug used by NavItem.to → module-presence key. Examples:
 *  '/boq'           → 'boq'
 *  '/clash'         → 'clash'
 *  '/bim/federations' → 'bim_federations' (slash → underscore)
 *  '/match-elements'  → 'match_elements'  (dash → underscore)
 *  '/'              → 'dashboard' (special-cased)
 *
 *  Query params and hash fragments are stripped — `/takeoff?tab=…`
 *  becomes `takeoff`, `/bim/rules?mode=requirements` becomes `bim_rules`. */
export function navToPresenceKey(to: string): string {
  if (to === '/' || to === '') return 'dashboard';
  const pathOnly = to.split('?')[0]!.split('#')[0]!;
  return pathOnly.replace(/^\/+/, '').replace(/[/-]/g, '_').toLowerCase();
}

/** Presence keys for company-wide registers and hybrid modules that must
 *  NEVER be dimmed just because the *active project* has no linked rows.
 *
 *  These surfaces hold data that lives above any single project:
 *   - company-wide registers (subcontractor directory, contacts,
 *     supplier catalogues, the equipment fleet, the portal user list)
 *     have no ``project_id`` at all;
 *   - hybrid modules (CRM opportunities, service contracts) may hold
 *     global/unlinked rows that exist before the record is tied to a
 *     delivery project.
 *
 *  The backend already shapes their booleans correctly (company-wide /
 *  hybrid probes - see ``module_presence.py``). This set is a frontend
 *  safety net so a probe regression can never grey-out a register that
 *  genuinely has data: for these keys we treat presence as "always show
 *  at full weight" rather than trusting a per-project flag (issue #228). */
const NEVER_DIM_BY_PROJECT_KEYS: ReadonlySet<string> = new Set([
  'crm',
  'subcontractors',
  'contacts',
  'supplier_catalogs',
  'equipment',
  'portal',
  'service',
]);

export interface ModulePresenceResult {
  /** Truthy when the project has data for this module. */
  isPopulated: (to: string) => boolean;
  /** Truthy when the hook hasn't loaded yet — sidebar renders normal. */
  isLoading: boolean;
  /** Raw map for callers that need it (e.g. analytics overlays). */
  presence: ModulePresenceMap;
}

const EMPTY_RESULT: ModulePresenceResult = {
  isPopulated: () => true, // default to "show normally" when unknown
  isLoading: false,
  presence: {},
};

export function useModulePresence(): ModulePresenceResult {
  const projectId = useProjectContextStore((s) => s.activeProjectId);

  const { data, isLoading } = useQuery<ModulePresenceMap>({
    queryKey: ['module-presence', projectId],
    queryFn: () =>
      apiGet<ModulePresenceMap>(
        `/v1/projects/${encodeURIComponent(projectId!)}/module-presence`,
      ),
    enabled: !!projectId,
    staleTime: 60_000,
    refetchInterval: 5 * 60_000, // 5 min — module-presence is sticky
    refetchOnWindowFocus: false,
  });

  if (!projectId) return EMPTY_RESULT;

  const presence: ModulePresenceMap = data ?? {};

  return {
    isPopulated: (to: string) => {
      // While loading: default to "populated" so no dimming flash.
      if (!data) return true;
      const key = navToPresenceKey(to);
      // Company-wide registers and hybrid modules are never dimmed by the
      // active project - their data lives above any single project, so a
      // project with no linked rows must still show them at full weight.
      if (NEVER_DIM_BY_PROJECT_KEYS.has(key)) return true;
      // Unknown keys (modules outside the backend's known set) default
      // to populated — better to show a row at full weight than to dim
      // something we can't classify.
      return presence[key] ?? true;
    },
    isLoading,
    presence,
  };
}

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Menu focus for packs that bring their own frame of modules.
 *
 * Choosing a framework pack (for example the eleven-area project frame) puts
 * that frame at the centre of the work, so the sidebar narrows to it: the
 * pack's own modules and our core modules (cost databases, estimates, the
 * takeoff and BIM tools and a few companions) stay, and every other row steps
 * out. The modules stay installed. Nothing new is stored: the rows are written
 * into the same per-user list the "Edit menu" editor uses (`useHiddenModules`),
 * so showing a row again in the editor is the only way back and that choice
 * persists like any other. Only rows the editor itself can hide are touched,
 * never whole sections and never the structural rows (dashboard, projects,
 * settings, users, about).
 *
 * One marker entry per pack (`pack:<slug>`) lives in the same list and records
 * that the pack has already had its say. It is what keeps the editor's choice:
 * with the marker present the pack never hides anything again, even if the
 * user showed every row. The marker is not a route and is never shown or
 * counted as a hidden row.
 */

/** Packs that hide the menu rows of the modules they select, by slug. */
export const MENU_HIDING_PACKS: readonly string[] = ['eleven-areas-framework'];

/**
 * Core sidebar rows that stay visible under a focusing pack: cost databases,
 * estimates, PDF and DWG takeoff, BIM, schedule, validation, tendering and
 * reports. A row below one of these (`/bim/rules`) stays with it.
 */
export const PACK_FOCUS_CORE_ROUTES: readonly string[] = [
  '/costs',
  '/boq',
  '/takeoff',
  '/dwg-takeoff',
  '/bim',
  '/schedule',
  '/validation',
  '/tenders',
  '/reports',
];

const MARKER_PREFIX = 'pack:';

/** True when the active pack is a framework pack whose modules the menu and the project hub offer. */
export function isFrameworkPackActive(
  pack: { active?: boolean; manifest?: { slug?: string | null } | null } | null | undefined,
): boolean {
  const slug = pack?.active ? pack.manifest?.slug : null;
  return !!slug && MENU_HIDING_PACKS.includes(slug);
}

export function packMarker(slug: string): string {
  return `${MARKER_PREFIX}${slug}`;
}

/** True for the bookkeeping entries that share the hidden list with routes. */
export function isMenuMarker(entry: string): boolean {
  return entry.startsWith(MARKER_PREFIX);
}

/** The hidden entries that are real rows, without the pack markers. */
export function visibleHiddenRoutes(hidden: readonly string[]): string[] {
  return hidden.filter((entry) => !isMenuMarker(entry));
}

/**
 * Sidebar routes served by any of the given modules.
 *
 * `routeModules` is the sidebar's route to backend module table; a value is
 * one module name or a list of them.
 */
export function routesOfModules(
  modules: readonly string[],
  routeModules: Record<string, string | readonly string[]>,
): string[] {
  const wanted = new Set(modules);
  const routes: string[] = [];
  for (const [route, owner] of Object.entries(routeModules)) {
    const owners = typeof owner === 'string' ? [owner] : owner;
    if (owners.some((name) => wanted.has(name))) routes.push(route);
  }
  return routes;
}

export interface PackMenuInput {
  /** The persisted hidden list as the menu editor sees it. */
  hidden: readonly string[];
  /** Slug of the active pack, or null when none is active. */
  activeSlug: string | null;
  /** Modules the active pack selects (`default_modules`). */
  packModules: readonly string[];
  routeModules: Record<string, string | readonly string[]>;
  /** Every sidebar route the "Edit menu" editor can hide. */
  hideableRoutes: readonly string[];
}

function isCoreRoute(route: string): boolean {
  const path = route.split('?')[0]!;
  return PACK_FOCUS_CORE_ROUTES.some((core) => path === core || path.startsWith(`${core}/`));
}

/**
 * The hidden list after the active pack has had its say (every hideable row
 * that is neither core nor served by a pack module is added), or null when there
 * is nothing to change (no hiding pack is active, or it already ran once).
 */
export function applyPackMenu(input: PackMenuInput): string[] | null {
  const { hidden, activeSlug, packModules, routeModules, hideableRoutes } = input;
  if (!activeSlug || !MENU_HIDING_PACKS.includes(activeSlug)) return null;
  const marker = packMarker(activeSlug);
  if (hidden.includes(marker)) return null;
  const known = new Set(hidden);
  const packRoutes = new Set(routesOfModules(packModules, routeModules));
  const added = hideableRoutes.filter(
    (route) => !known.has(route) && !packRoutes.has(route) && !isCoreRoute(route),
  );
  return [...hidden, marker, ...added];
}

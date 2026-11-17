/**
 * Phase and project-type filters shared by every cross-project view (#567).
 *
 * Phase is the lifecycle stage (tender, construction, operation), project type
 * the free-text building or work type. Both are optional on a project, so a
 * filter offers an explicit "not set" choice instead of dropping those rows.
 * Opt-in: nothing here hides data unless a view applies it.
 */

export const FACET_ALL = 'all';
export const FACET_UNSET = '__unset__';

export type ProjectFacetKey = 'phase' | 'project_type';

export interface ProjectFacetFilters {
  phase: string;
  project_type: string;
}

export const EMPTY_FACETS: ProjectFacetFilters = { phase: FACET_ALL, project_type: FACET_ALL };

type Faceted = { phase?: string | null; project_type?: string | null };

function clean(value: string | null | undefined): string {
  return typeof value === 'string' ? value.trim() : '';
}

/** Distinct values present on the given projects, sorted, with FACET_UNSET last when any row has none. */
export function facetOptions(projects: readonly Faceted[], key: ProjectFacetKey): string[] {
  const values = new Set<string>();
  let unset = false;
  for (const project of projects) {
    const value = clean(project?.[key]);
    if (value) values.add(value);
    else unset = true;
  }
  const sorted = [...values].sort((a, b) => a.localeCompare(b));
  // "Not set" is only a choice when it narrows something; on its own it is the whole list.
  if (unset && sorted.length > 0) sorted.push(FACET_UNSET);
  return sorted;
}

export function matchesFacet(value: string | null | undefined, filter: string | undefined): boolean {
  if (!filter || filter === FACET_ALL) return true;
  const own = clean(value);
  if (filter === FACET_UNSET) return own === '';
  return own === filter;
}

export function applyProjectFacets<T extends Faceted>(projects: readonly T[], filters: Partial<ProjectFacetFilters>): T[] {
  return projects.filter(
    (p) => matchesFacet(p.phase, filters.phase) && matchesFacet(p.project_type, filters.project_type),
  );
}

export function isFacetFilterActive(filters: Partial<ProjectFacetFilters> | undefined): boolean {
  if (!filters) return false;
  return (
    (!!filters.phase && filters.phase !== FACET_ALL) ||
    (!!filters.project_type && filters.project_type !== FACET_ALL)
  );
}

/** Query string (with leading ?) that makes the analytics endpoint total only the filtered projects. */
export function analyticsFacetParams(filters: Partial<ProjectFacetFilters>): string {
  const params = new URLSearchParams();
  if (filters.phase && filters.phase !== FACET_ALL) params.set('phase', filters.phase);
  if (filters.project_type && filters.project_type !== FACET_ALL) params.set('project_type', filters.project_type);
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

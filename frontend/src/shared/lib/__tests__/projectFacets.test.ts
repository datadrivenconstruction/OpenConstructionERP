import { describe, expect, it } from 'vitest';

import {
  EMPTY_FACETS,
  FACET_ALL,
  FACET_UNSET,
  analyticsFacetParams,
  applyProjectFacets,
  facetOptions,
  isFacetFilterActive,
  matchesFacet,
} from '../projectFacets';

const projects = [
  { id: 'a', phase: 'tender', project_type: 'Residential' },
  { id: 'b', phase: 'construction', project_type: 'Infrastructure' },
  { id: 'c', phase: 'operation', project_type: 'Residential' },
  { id: 'd', phase: null, project_type: '  ' },
  { id: 'e', phase: 'tender', project_type: 'Custom warehouse' },
];

describe('project phase and type filters', () => {
  it('offers every value present, custom ones included, and "not set" last', () => {
    expect(facetOptions(projects, 'phase')).toEqual(['construction', 'operation', 'tender', FACET_UNSET]);
    expect(facetOptions(projects, 'project_type')).toEqual([
      'Custom warehouse',
      'Infrastructure',
      'Residential',
      FACET_UNSET,
    ]);
  });

  it('offers nothing when no project carries the field', () => {
    expect(facetOptions([{ phase: null }, {}], 'phase')).toEqual([]);
  });

  it('combines phase and type', () => {
    const ids = applyProjectFacets(projects, { phase: 'tender', project_type: 'Residential' }).map((p) => p.id);
    expect(ids).toEqual(['a']);
  });

  it('finds projects with no value under "not set" instead of dropping them', () => {
    expect(applyProjectFacets(projects, { phase: FACET_UNSET }).map((p) => p.id)).toEqual(['d']);
    expect(applyProjectFacets(projects, { project_type: FACET_UNSET }).map((p) => p.id)).toEqual(['d']);
  });

  it('returns an empty list for a combination nobody has, and everything after reset', () => {
    expect(applyProjectFacets(projects, { phase: 'operation', project_type: 'Infrastructure' })).toEqual([]);
    expect(applyProjectFacets(projects, EMPTY_FACETS)).toHaveLength(projects.length);
  });

  it('treats "all" and a missing filter as no filter', () => {
    expect(matchesFacet(null, FACET_ALL)).toBe(true);
    expect(matchesFacet('tender', undefined)).toBe(true);
    expect(isFacetFilterActive(EMPTY_FACETS)).toBe(false);
    expect(isFacetFilterActive({ phase: 'tender' })).toBe(true);
  });

  it('builds analytics query params only for active facets', () => {
    expect(analyticsFacetParams(EMPTY_FACETS)).toBe('');
    expect(analyticsFacetParams({ phase: 'tender', project_type: FACET_ALL })).toBe('?phase=tender');
    expect(analyticsFacetParams({ phase: FACET_UNSET, project_type: 'Office block' })).toBe(
      '?phase=__unset__&project_type=Office+block',
    );
  });
});

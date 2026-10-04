/**
 * A link to one container must reach it even past the register's first page.
 *
 * The list endpoint answers 50 containers by default and the register never
 * pages, so the container a "published" notification names is often not in
 * the rows the page holds. These cases pin the merge the page draws from.
 */
import { describe, expect, it } from 'vitest';

import type { CDEContainer } from './api';
import { withFocusedContainer } from './focusedContainer';

const PROJECT = 'p-1';

function container(id: string, overrides: Partial<CDEContainer> = {}): CDEContainer {
  return {
    id,
    project_id: PROJECT,
    container_code: `A-${id}`,
    title: `Drawing ${id}`,
    description: null,
    discipline_code: null,
    cde_state: 'published',
    suitability_code: null,
    current_revision_id: null,
    classification_code: null,
    classification_system: null,
    originator_code: null,
    security_classification: null,
    created_by: null,
    metadata: {},
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    ...overrides,
  };
}

// The first page of a long register: containers 1..50.
const firstPage = Array.from({ length: 50 }, (_, i) => container(String(i + 1)));
const scope = { projectId: PROJECT, stateFilter: '' as const, searchQuery: '' };

describe('withFocusedContainer', () => {
  it('pins a linked container the first page does not hold, on top', () => {
    const linked = container('120');
    const rows = withFocusedContainer(firstPage, linked, scope);
    expect(rows).toHaveLength(51);
    expect(rows[0]!.id).toBe('120');
    expect(rows.slice(1)).toEqual(firstPage);
  });

  it('leaves the rows alone when the container is already listed', () => {
    const listed = firstPage[9]!;
    expect(withFocusedContainer(firstPage, listed, scope)).toBe(firstPage);
  });

  it('leaves the rows alone when nothing is focused', () => {
    expect(withFocusedContainer(firstPage, null, scope)).toBe(firstPage);
    expect(withFocusedContainer(firstPage, undefined, scope)).toBe(firstPage);
  });

  it('never pins a container of another project', () => {
    const foreign = container('120', { project_id: 'p-2' });
    expect(withFocusedContainer(firstPage, foreign, scope)).toBe(firstPage);
  });

  it('respects the active state tab', () => {
    const shared = container('120', { cde_state: 'shared' });
    expect(withFocusedContainer(firstPage, shared, { ...scope, stateFilter: 'published' })).toBe(firstPage);
    expect(withFocusedContainer(firstPage, shared, { ...scope, stateFilter: 'shared' })[0]!.id).toBe('120');
  });

  it('steps aside while someone is searching', () => {
    expect(withFocusedContainer(firstPage, container('120'), { ...scope, searchQuery: 'slab' })).toBe(firstPage);
    // Whitespace is not a search.
    expect(withFocusedContainer(firstPage, container('120'), { ...scope, searchQuery: '  ' })).toHaveLength(51);
  });

  it('shows the linked container even when the list came back empty', () => {
    expect(withFocusedContainer([], container('120'), scope).map((c) => c.id)).toEqual(['120']);
  });
});

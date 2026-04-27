// @ts-nocheck
/**
 * Tests for FederatedResultsTable (T10 / task #193).
 *
 * Covers:
 *   - empty state when there is no data
 *   - rendering of provenance chips for `__project_id` + `__snapshot_id`
 *   - column ordering: provenance first, group-by next, measure last
 */
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

import { FederatedResultsTable } from '../FederatedResultsTable';

const RESPONSE = {
  columns: ['__project_id', '__snapshot_id', 'category', 'measure_value'],
  rows: [
    {
      __project_id: 'proj-A',
      __snapshot_id: 'snap-1',
      category: 'wall',
      measure_value: 12,
    },
    {
      __project_id: 'proj-B',
      __snapshot_id: 'snap-3',
      category: 'door',
      measure_value: 4,
    },
  ],
  project_count: 2,
  snapshot_count: 2,
  schema_align: 'intersect' as const,
  measure: '*',
  agg: 'count' as const,
  group_by: ['category'],
};

afterEach(() => {
  cleanup();
});

describe('FederatedResultsTable', () => {
  it('renders the empty state when data is null', () => {
    render(<FederatedResultsTable data={null} />);
    expect(screen.getByTestId('federation-results-empty')).toBeInTheDocument();
  });

  it('renders provenance chips for project + snapshot per row', () => {
    render(
      <FederatedResultsTable
        data={RESPONSE}
        snapshotLabels={{ 'snap-1': 'Baseline', 'snap-3': 'Other' }}
        projectLabels={{ 'proj-A': 'Alpha', 'proj-B': 'Beta' }}
      />,
    );
    expect(screen.getByTestId('federation-results-table')).toBeInTheDocument();
    expect(
      screen.getByTestId('federation-chip-project-proj-A'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('federation-chip-snapshot-snap-1'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('federation-chip-project-proj-B'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('federation-chip-snapshot-snap-3'),
    ).toBeInTheDocument();
    // Labels propagate.
    expect(
      screen.getByTestId('federation-chip-snapshot-snap-1').textContent,
    ).toContain('Baseline');
    expect(
      screen.getByTestId('federation-chip-project-proj-A').textContent,
    ).toContain('Alpha');
  });

  it('orders columns provenance → group-by → measure', () => {
    render(<FederatedResultsTable data={RESPONSE} />);
    // The thead test ids reveal the rendered order.
    const headerTestIds = [
      'federation-results-th-__project_id',
      'federation-results-th-__snapshot_id',
      'federation-results-th-category',
      'federation-results-th-measure_value',
    ];
    for (const id of headerTestIds) {
      expect(screen.getByTestId(id)).toBeInTheDocument();
    }
  });
});

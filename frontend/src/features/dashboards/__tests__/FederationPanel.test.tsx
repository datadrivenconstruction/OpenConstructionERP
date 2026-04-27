// @ts-nocheck
/**
 * Tests for FederationPanel (T10 / task #193).
 *
 * Covers:
 *   - selecting snapshots toggles chips
 *   - "Build view" calls buildFederation with the selected ids + mode
 *   - "Run aggregate" calls federatedAggregate after a build, and
 *     surfaces the resulting rows through FederatedResultsTable
 *   - server-side errors surface in the error banner
 */
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest';
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    buildFederation: vi.fn(),
    federatedAggregate: vi.fn(),
  };
});

import { buildFederation, federatedAggregate } from '../api';
import { FederationPanel } from '../FederationPanel';

const SNAPSHOTS = [
  { id: 'snap-1', label: 'Baseline', projectId: 'proj-A', projectLabel: 'A' },
  { id: 'snap-2', label: 'Updated', projectId: 'proj-A', projectLabel: 'A' },
  { id: 'snap-3', label: 'Other', projectId: 'proj-B', projectLabel: 'B' },
];

const BUILD_RESPONSE = {
  view_name: 'federated_abc',
  columns: ['entity_guid', 'category', 'area_m2', '__project_id', '__snapshot_id'],
  dtypes: {},
  project_count: 2,
  snapshot_count: 2,
  row_count: 5,
  schema_align: 'intersect' as const,
  snapshots: [
    { snapshot_id: 'snap-1', project_id: 'proj-A' },
    { snapshot_id: 'snap-3', project_id: 'proj-B' },
  ],
};

const AGGREGATE_RESPONSE = {
  columns: ['__project_id', '__snapshot_id', 'category', 'measure_value'],
  rows: [
    {
      __project_id: 'proj-A',
      __snapshot_id: 'snap-1',
      category: 'wall',
      measure_value: 3,
    },
    {
      __project_id: 'proj-B',
      __snapshot_id: 'snap-3',
      category: 'wall',
      measure_value: 2,
    },
  ],
  project_count: 2,
  snapshot_count: 2,
  schema_align: 'intersect' as const,
  measure: '*',
  agg: 'count' as const,
  group_by: ['category'],
};

beforeEach(() => {
  (buildFederation as ReturnType<typeof vi.fn>).mockReset();
  (federatedAggregate as ReturnType<typeof vi.fn>).mockReset();
});

afterEach(() => {
  cleanup();
});

function renderPanel(
  props?: Partial<React.ComponentProps<typeof FederationPanel>>,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <FederationPanel
        available={SNAPSHOTS}
        initialSelection={[]}
        {...props}
      />
    </QueryClientProvider>,
  );
}

describe('FederationPanel', () => {
  it('toggles snapshot chips on click', () => {
    renderPanel();

    fireEvent.click(screen.getByTestId('federation-snapshot-option-snap-1'));
    expect(
      screen.getByTestId('federation-chip-snap-1'),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('federation-snapshot-option-snap-3'));
    expect(
      screen.getByTestId('federation-chip-snap-3'),
    ).toBeInTheDocument();

    // Toggle off
    fireEvent.click(screen.getByTestId('federation-snapshot-option-snap-1'));
    expect(
      screen.queryByTestId('federation-chip-snap-1'),
    ).not.toBeInTheDocument();
  });

  it('calls buildFederation with the selected ids and chosen schema mode', async () => {
    (buildFederation as ReturnType<typeof vi.fn>).mockResolvedValue(BUILD_RESPONSE);
    renderPanel();

    fireEvent.click(screen.getByTestId('federation-snapshot-option-snap-1'));
    fireEvent.click(screen.getByTestId('federation-snapshot-option-snap-3'));
    fireEvent.change(screen.getByTestId('federation-schema-align'), {
      target: { value: 'union' },
    });
    fireEvent.click(screen.getByTestId('federation-build-btn'));

    await waitFor(() => {
      expect(buildFederation).toHaveBeenCalledTimes(1);
    });
    expect(buildFederation).toHaveBeenCalledWith({
      snapshotIds: ['snap-1', 'snap-3'],
      schemaAlign: 'union',
    });

    // The view summary appears after a successful build.
    await waitFor(() =>
      expect(screen.getByTestId('federation-view-summary')).toBeInTheDocument(),
    );
  });

  it('runs the aggregate after a build and renders the results table', async () => {
    (buildFederation as ReturnType<typeof vi.fn>).mockResolvedValue(BUILD_RESPONSE);
    (federatedAggregate as ReturnType<typeof vi.fn>).mockResolvedValue(
      AGGREGATE_RESPONSE,
    );
    renderPanel();

    fireEvent.click(screen.getByTestId('federation-snapshot-option-snap-1'));
    fireEvent.click(screen.getByTestId('federation-build-btn'));
    await waitFor(() =>
      expect(screen.getByTestId('federation-view-summary')).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByTestId('federation-group-by'), {
      target: { value: 'category' },
    });
    fireEvent.click(screen.getByTestId('federation-aggregate-btn'));

    await waitFor(() => expect(federatedAggregate).toHaveBeenCalled());
    expect(federatedAggregate).toHaveBeenCalledWith(
      expect.objectContaining({
        snapshotIds: ['snap-1'],
        schemaAlign: 'intersect',
        groupBy: ['category'],
        measure: '*',
        agg: 'count',
      }),
    );

    await waitFor(() =>
      expect(screen.getByTestId('federation-results-table')).toBeInTheDocument(),
    );
    // Two provenance chips visible (one per snapshot in the response).
    expect(
      screen.getByTestId('federation-chip-snapshot-snap-1'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('federation-chip-snapshot-snap-3'),
    ).toBeInTheDocument();
  });

  it('surfaces a server error in the error banner', async () => {
    (buildFederation as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('Schemas mismatch under strict alignment'),
    );
    renderPanel();

    fireEvent.click(screen.getByTestId('federation-snapshot-option-snap-1'));
    fireEvent.click(screen.getByTestId('federation-build-btn'));

    await waitFor(() =>
      expect(screen.getByTestId('federation-error')).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId('federation-error').textContent,
    ).toContain('Schemas mismatch');
  });
});

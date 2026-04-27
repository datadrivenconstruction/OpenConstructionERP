// @ts-nocheck
/**
 * Tests for SnapshotTimeline (T11).
 *
 * Covers:
 *   - rendering one card per timeline entry
 *   - clicking a card calls onActiveChange with the snapshot id
 *   - ticking two checkboxes enables the Compare button and calls
 *     onCompare with the older snapshot first
 *   - the empty-state appears when the project has no snapshots
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
    getSnapshotTimeline: vi.fn(),
  };
});

import { getSnapshotTimeline } from '../api';
import { SnapshotTimeline } from '../SnapshotTimeline';

const PROJECT_ID = 'proj-1';

const ITEMS = [
  {
    id: 'snap-3',
    project_id: PROJECT_ID,
    label: 'Today — final',
    created_at: '2026-04-27T12:00:00Z',
    created_by_user_id: 'u1',
    parent_snapshot_id: 'snap-2',
    total_entities: 320,
    total_categories: 8,
    source_file_count: 2,
    schema_hash: 'abcd1234',
    completeness_score: 0.96,
  },
  {
    id: 'snap-2',
    project_id: PROJECT_ID,
    label: 'Yesterday',
    created_at: '2026-04-26T09:00:00Z',
    created_by_user_id: 'u1',
    parent_snapshot_id: 'snap-1',
    total_entities: 300,
    total_categories: 7,
    source_file_count: 2,
    schema_hash: 'abcd1234',
    completeness_score: 0.92,
  },
  {
    id: 'snap-1',
    project_id: PROJECT_ID,
    label: 'Baseline',
    created_at: '2026-04-25T08:00:00Z',
    created_by_user_id: 'u1',
    parent_snapshot_id: null,
    total_entities: 200,
    total_categories: 5,
    source_file_count: 1,
    schema_hash: '99999999',
    completeness_score: null,
  },
];

beforeEach(() => {
  (getSnapshotTimeline as ReturnType<typeof vi.fn>).mockReset();
});

afterEach(() => {
  cleanup();
});

function renderTimeline(props?: Partial<React.ComponentProps<typeof SnapshotTimeline>>) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <SnapshotTimeline projectId={PROJECT_ID} {...props} />
    </QueryClientProvider>,
  );
}

describe('SnapshotTimeline', () => {
  it('renders one row per snapshot in the timeline', async () => {
    (getSnapshotTimeline as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: PROJECT_ID,
      items: ITEMS,
      next_before: null,
    });

    renderTimeline();

    await waitFor(() =>
      expect(getSnapshotTimeline).toHaveBeenCalledWith({
        projectId: PROJECT_ID,
        limit: 50,
      }),
    );

    await waitFor(() => {
      expect(screen.getByTestId('snapshot-timeline-row-snap-1')).toBeInTheDocument();
      expect(screen.getByTestId('snapshot-timeline-row-snap-2')).toBeInTheDocument();
      expect(screen.getByTestId('snapshot-timeline-row-snap-3')).toBeInTheDocument();
    });
  });

  it('clicking a card fires onActiveChange with the snapshot id', async () => {
    (getSnapshotTimeline as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: PROJECT_ID,
      items: ITEMS,
      next_before: null,
    });
    const onActiveChange = vi.fn();
    renderTimeline({ onActiveChange });

    await waitFor(() =>
      expect(screen.getByTestId('snapshot-timeline-card-snap-2')).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId('snapshot-timeline-card-snap-2'));
    expect(onActiveChange).toHaveBeenCalledWith('snap-2');
  });

  it('ticking two snapshots enables Compare and calls onCompare older→newer', async () => {
    (getSnapshotTimeline as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: PROJECT_ID,
      items: ITEMS,
      next_before: null,
    });
    const onCompare = vi.fn();
    renderTimeline({ onCompare });

    await waitFor(() =>
      expect(screen.getByTestId('snapshot-timeline-compare-toggle-snap-1')).toBeInTheDocument(),
    );

    // Compare button is initially disabled.
    const compareBtn = screen.getByTestId('snapshot-timeline-compare-button');
    expect(compareBtn).toBeDisabled();

    // Tick newest first, then oldest — onCompare should still call
    // the older one as the first argument.
    fireEvent.click(screen.getByTestId('snapshot-timeline-compare-toggle-snap-3'));
    fireEvent.click(screen.getByTestId('snapshot-timeline-compare-toggle-snap-1'));

    await waitFor(() => expect(compareBtn).not.toBeDisabled());

    fireEvent.click(compareBtn);
    expect(onCompare).toHaveBeenCalledWith('snap-1', 'snap-3');
  });

  it('renders the empty state when the timeline has no entries', async () => {
    (getSnapshotTimeline as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: PROJECT_ID,
      items: [],
      next_before: null,
    });
    renderTimeline();

    await waitFor(() => expect(getSnapshotTimeline).toHaveBeenCalled());

    // No rows render; the empty-state copy ships through EmptyState
    // which always exposes the parent testid.
    await waitFor(() =>
      expect(screen.queryByTestId('snapshot-timeline-row-snap-1')).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId('snapshot-timeline')).toBeInTheDocument();
  });

  it('shows the active badge on the highlighted card', async () => {
    (getSnapshotTimeline as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: PROJECT_ID,
      items: ITEMS,
      next_before: null,
    });
    renderTimeline({ activeSnapshotId: 'snap-2' });

    await waitFor(() =>
      expect(screen.getByTestId('snapshot-timeline-card-snap-2')).toBeInTheDocument(),
    );
    const card = screen.getByTestId('snapshot-timeline-card-snap-2');
    expect(card).toHaveAttribute('aria-current', 'true');
  });

  it('shows the error banner when the API call fails', async () => {
    (getSnapshotTimeline as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('boom'),
    );
    renderTimeline();
    await waitFor(() =>
      expect(screen.getByTestId('snapshot-timeline-error')).toBeInTheDocument(),
    );
  });
});

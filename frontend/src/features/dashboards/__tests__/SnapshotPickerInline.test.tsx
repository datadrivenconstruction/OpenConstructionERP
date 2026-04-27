// @ts-nocheck
/**
 * Tests for SnapshotPickerInline (T11).
 *
 * Covers:
 *   - the trigger button shows the active snapshot's label
 *   - clicking the trigger opens the listbox with all snapshots
 *   - picking a snapshot fires onChange with the new id and closes
 *     the listbox
 *   - the empty-state copy renders when the project has no snapshots
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
import { SnapshotPickerInline } from '../SnapshotPickerInline';

const PROJECT_ID = 'proj-1';

const ITEMS = [
  {
    id: 'snap-3',
    project_id: PROJECT_ID,
    label: 'Today — final',
    created_at: '2026-04-27T12:00:00Z',
    created_by_user_id: 'u1',
    parent_snapshot_id: null,
    total_entities: 320,
    total_categories: 8,
    source_file_count: 2,
    schema_hash: null,
    completeness_score: null,
  },
  {
    id: 'snap-2',
    project_id: PROJECT_ID,
    label: 'Yesterday',
    created_at: '2026-04-26T12:00:00Z',
    created_by_user_id: 'u1',
    parent_snapshot_id: null,
    total_entities: 300,
    total_categories: 7,
    source_file_count: 1,
    schema_hash: null,
    completeness_score: null,
  },
];

beforeEach(() => {
  (getSnapshotTimeline as ReturnType<typeof vi.fn>).mockReset();
});

afterEach(() => {
  cleanup();
});

function renderPicker(props?: Partial<React.ComponentProps<typeof SnapshotPickerInline>>) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const onChange = props?.onChange ?? vi.fn();
  const utils = render(
    <QueryClientProvider client={client}>
      <SnapshotPickerInline
        projectId={PROJECT_ID}
        activeSnapshotId={props?.activeSnapshotId ?? null}
        onChange={onChange}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { ...utils, onChange };
}

describe('SnapshotPickerInline', () => {
  it('shows the active snapshot label in the trigger', async () => {
    (getSnapshotTimeline as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: PROJECT_ID,
      items: ITEMS,
      next_before: null,
    });
    renderPicker({ activeSnapshotId: 'snap-3' });

    await waitFor(() =>
      expect(getSnapshotTimeline).toHaveBeenCalled(),
    );

    await waitFor(() => {
      expect(
        screen.getByTestId('snapshot-picker-inline-current').textContent,
      ).toContain('Today — final');
    });
  });

  it('clicking the trigger opens the listbox and clicking an option fires onChange', async () => {
    (getSnapshotTimeline as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: PROJECT_ID,
      items: ITEMS,
      next_before: null,
    });
    const { onChange } = renderPicker({ activeSnapshotId: 'snap-3' });

    await waitFor(() => expect(getSnapshotTimeline).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId('snapshot-picker-inline-trigger'));

    await waitFor(() =>
      expect(screen.getByTestId('snapshot-picker-inline-listbox')).toBeInTheDocument(),
    );

    expect(
      screen.getByTestId('snapshot-picker-inline-option-snap-2'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('snapshot-picker-inline-option-snap-3'),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('snapshot-picker-inline-option-snap-2'));
    expect(onChange).toHaveBeenCalledWith('snap-2');

    // Listbox closes after picking.
    await waitFor(() =>
      expect(
        screen.queryByTestId('snapshot-picker-inline-listbox'),
      ).not.toBeInTheDocument(),
    );
  });

  it('renders the empty-state copy when the project has no snapshots', async () => {
    (getSnapshotTimeline as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: PROJECT_ID,
      items: [],
      next_before: null,
    });
    renderPicker();

    await waitFor(() => expect(getSnapshotTimeline).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId('snapshot-picker-inline-trigger'));

    await waitFor(() =>
      expect(
        screen.getByTestId('snapshot-picker-inline-empty'),
      ).toBeInTheDocument(),
    );
  });

  it('falls back to a placeholder label when no snapshot is active yet', async () => {
    (getSnapshotTimeline as ReturnType<typeof vi.fn>).mockResolvedValue({
      project_id: PROJECT_ID,
      items: ITEMS,
      next_before: null,
    });
    renderPicker({ activeSnapshotId: null });

    await waitFor(() => expect(getSnapshotTimeline).toHaveBeenCalled());

    await waitFor(() => {
      const current = screen.getByTestId('snapshot-picker-inline-current')
        .textContent;
      // Active label is null, so the fallback i18n copy renders.
      // The test bundle is not loaded, so the defaultValue surfaces.
      expect(current).toMatch(/no snapshot|loading/i);
    });
  });
});

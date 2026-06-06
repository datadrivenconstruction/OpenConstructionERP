// @ts-nocheck
/**
 * Tests for the CONN-73 snapshot connectivity deep links on SnapshotsPage.
 *
 * Covers:
 *   - each snapshot card exposes a "Match to cost" and a "Takeoff" action
 *   - "Match to cost" navigates to /match-elements carrying the active
 *     project (the wizard reads ?project=)
 *   - "Takeoff" navigates to /takeoff?tab=documents
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

const navigateMock = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual =
    await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    listSnapshots: vi.fn(),
  };
});

import { MemoryRouter } from 'react-router-dom';
import { listSnapshots } from '../api';
import { SnapshotsPage } from '../SnapshotsPage';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

const PROJECT_ID = 'proj-77';

const SNAPSHOTS = [
  {
    id: 'snap-a',
    project_id: PROJECT_ID,
    label: 'Rev A',
    total_entities: 320,
    total_categories: 8,
    summary_stats: {},
    created_by_user_id: 'u1',
    created_at: '2026-04-27T12:00:00Z',
  },
];

beforeEach(() => {
  navigateMock.mockReset();
  (listSnapshots as ReturnType<typeof vi.fn>).mockReset();
  (listSnapshots as ReturnType<typeof vi.fn>).mockResolvedValue({
    total: SNAPSHOTS.length,
    items: SNAPSHOTS,
  });
  useProjectContextStore.getState().setActiveProject(PROJECT_ID, 'Demo project');
});

afterEach(() => {
  cleanup();
});

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SnapshotsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('SnapshotsPage CONN-73 deep links', () => {
  it('renders match-to-cost and takeoff actions per snapshot card', async () => {
    renderPage();
    await waitFor(() => expect(listSnapshots).toHaveBeenCalledWith(PROJECT_ID));
    await waitFor(() =>
      expect(screen.getByTestId('snapshot-match-snap-a')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('snapshot-takeoff-snap-a')).toBeInTheDocument();
  });

  it('match-to-cost navigates to /match-elements carrying the active project', async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId('snapshot-match-snap-a')).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId('snapshot-match-snap-a'));
    expect(navigateMock).toHaveBeenCalledWith(
      `/match-elements?project=${PROJECT_ID}`,
    );
  });

  it('takeoff navigates to /takeoff?tab=documents', async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByTestId('snapshot-takeoff-snap-a')).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId('snapshot-takeoff-snap-a'));
    expect(navigateMock).toHaveBeenCalledWith('/takeoff?tab=documents');
  });
});

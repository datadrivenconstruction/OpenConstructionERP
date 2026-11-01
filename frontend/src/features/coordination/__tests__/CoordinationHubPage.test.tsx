// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * CoordinationHubPage integration tests.
 *
 * The page fans out three React-Query calls (dashboard / matrix /
 * timeline) and composes the three sub-components. We stub ``apiGet`` so
 * the tests run offline and ``useActiveProjectProfile`` so we can pin
 * the active-project state.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  render,
  screen,
  waitFor,
  cleanup,
  fireEvent,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';

// Partial mock — keep ``getErrorMessage`` (and any other shared helpers
// RecoveryCard reaches for) so the error-banner test isn't faking out
// the entire api module. Without the spread, vi.mock replaced the
// whole module and RecoveryCard threw "getErrorMessage is not a
// function" the moment the all-fetch-fail test rendered it.
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>(
    '@/shared/lib/api',
  );
  return {
    ...actual,
    apiGet: vi.fn(),
  };
});

const navigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return {
    ...actual,
    useNavigate: () => navigate,
  };
});

// Project-profile hook — pin the active project id.
const projectIdRef: { current: string | null } = { current: 'p-1' };
vi.mock('@/features/projects/useProjectProfile', () => ({
  useActiveProjectProfile: () => ({
    projectId: projectIdRef.current,
    profile: undefined,
    isLoading: false,
  }),
}));

// MoneyDisplay reads preferences — same shim as in KPI test.
const __mockPrefState = { currency: 'EUR', numberLocale: 'en-US' };
vi.mock('@/stores/usePreferencesStore', async (importOriginal) => ({
  // Keep the real exports so a newly added one never breaks this mock.
  ...(await importOriginal<Record<string, unknown>>()),
  usePreferencesStore: (sel?: (s: unknown) => unknown) =>
    sel ? sel(__mockPrefState) : __mockPrefState,
  // Money surfaces resolve the locale through this rather than off the raw
  // preference, so a wholesale mock of the store has to carry it too, and it
  // has to carry both shapes. The hook is for components; the plain call is
  // for the formatters in `shared/lib`, which run during render but are not
  // components and cannot hold a hook. A mock with only one of the pair
  // throws on the other, and the message it throws names the mock rather than
  // the line that reached for it.
  useNumberLocale: () => __mockPrefState.numberLocale,
  getNumberLocale: () => __mockPrefState.numberLocale,
}));

import { apiGet } from '@/shared/lib/api';
import { CoordinationHubPage } from '../CoordinationHubPage';

const apiGetMock = apiGet as unknown as ReturnType<typeof vi.fn>;

const DASHBOARD = {
  project_id: 'p-1',
  currency: 'EUR',
  as_of: '2026-05-21T14:30:00Z',
  federations: { count: 2, total_members: 6, total_elements: 1000 },
  clashes: {
    open_count: 5,
    resolved_count: 10,
    ignored_count: 0,
    delta_since_last_run: { new: 2, resolved: 1, reopened: 0 },
    last_run_at: '2026-05-21T13:00:00Z',
  },
  rule_packs: {
    installed_count: 1,
    last_check_pass_count: 100,
    last_check_fail_count: 5,
    last_check_at: null,
  },
  smart_views: { user_count: 0, project_count: 1 },
  bcf_activity: {
    topics_exported_30d: 3,
    topics_imported_30d: 1,
    last_export_at: null,
  },
  open_cost_impact_total: 1000,
};

const MATRIX = {
  project_id: 'p-1',
  trades: ['arch', 'struct', 'mep', 'landscape', 'civil', 'other'],
  cells: [{ row: 'arch', col: 'struct', count: 3, open: 2, resolved: 1 }],
};

const TIMELINE = {
  project_id: 'p-1',
  events: [
    {
      ts: '2026-05-21T12:00:00Z',
      type: 'clash_run',
      summary: 'Run X completed - 5 clashes',
      user_id: 'u-1',
      target: '/clash?run=r1',
    },
    {
      ts: '2026-05-21T11:00:00Z',
      type: 'federation_created',
      summary: "Federation 'F1' created",
      user_id: null,
      target: '/bim/federations',
    },
  ],
};

function configureMocks() {
  apiGetMock.mockImplementation((url: string) => {
    if (url.includes('/dashboard')) return Promise.resolve(DASHBOARD);
    if (url.includes('/trade-matrix')) return Promise.resolve(MATRIX);
    if (url.includes('/timeline')) return Promise.resolve(TIMELINE);
    return Promise.reject(new Error('unexpected url'));
  });
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <CoordinationHubPage />
      </BrowserRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  navigate.mockReset();
  projectIdRef.current = 'p-1';
  cleanup();
});

describe('CoordinationHubPage', () => {
  it('renders the empty state when no project is selected', () => {
    projectIdRef.current = null;
    renderPage();
    expect(screen.getByTestId('coordination-no-project')).toBeInTheDocument();
  });

  it('renders the KPI cards with fetched data', async () => {
    configureMocks();
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('coordination-kpi-cards')).toBeInTheDocument();
    });
    expect(screen.getByTestId('kpi-open-clashes')).toHaveTextContent('5');
  });

  it('renders the trade matrix with fetched data', async () => {
    configureMocks();
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByTestId('coordination-trade-matrix'),
      ).toBeInTheDocument();
    });
    expect(screen.getByTestId('matrix-cell-arch-struct')).toHaveTextContent(
      '2',
    );
  });

  it('renders timeline events with fetched data', async () => {
    configureMocks();
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/Run X completed/)).toBeInTheDocument();
    });
    expect(screen.getByText(/Federation 'F1' created/)).toBeInTheDocument();
  });

  it('shows the as-of timestamp', async () => {
    configureMocks();
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('coordination-as-of')).toBeInTheDocument();
    });
  });

  it('shows the loading skeleton before data lands', () => {
    apiGetMock.mockImplementation(() => new Promise(() => {}));
    renderPage();
    expect(screen.getByTestId('coordination-kpi-skeleton')).toBeInTheDocument();
  });

  it('renders the error banner when every fetch fails', async () => {
    apiGetMock.mockRejectedValue(new Error('boom'));
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('coordination-error')).toBeInTheDocument();
    });
  });

  it('refresh button is wired (renders + clickable)', async () => {
    configureMocks();
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('coordination-refresh')).toBeInTheDocument();
    });
    const refresh = screen.getByTestId('coordination-refresh');
    fireEvent.click(refresh);
    // Triggers refetch on all three queries — at least 3 more apiGet calls.
    await waitFor(() => {
      // Initial 3 fetches + refresh triggers 3 more.
      expect(apiGetMock.mock.calls.length).toBeGreaterThanOrEqual(3);
    });
  });

  it('navigates from a trade-matrix cell to /clash', async () => {
    configureMocks();
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('matrix-cell-arch-struct')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('matrix-cell-arch-struct'));
    expect(navigate).toHaveBeenCalledWith(
      '/clash?project=p-1&disciplineA=arch&disciplineB=struct',
    );
  });

  it('shows the project-missing empty state when every endpoint 404s', async () => {
    // Simulates a stale ``oe_active_project`` localStorage entry pointing
    // at a project that was deleted or that the user no longer has access
    // to. Previously surfaced as a generic "Couldn't load this" — now
    // routes the user to /projects with a self-explanatory empty state.
    const stale = Object.assign(new Error('Project not found'), { status: 404 });
    apiGetMock.mockRejectedValue(stale);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByTestId('coordination-project-missing'),
      ).toBeInTheDocument();
    });
    // The legacy "all-three-error" full-page card MUST NOT render — the
    // missing-project branch takes precedence so the user sees a CTA
    // instead of a retry-card dead-end.
    expect(screen.queryByTestId('coordination-error')).not.toBeInTheDocument();
  });

  it('renders the export-CSV button in the header', async () => {
    configureMocks();
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('coordination-export')).toBeInTheDocument();
    });
  });

  it('renders the timeline window selector and re-queries on change', async () => {
    configureMocks();
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByTestId('coordination-timeline-window-7'),
      ).toBeInTheDocument();
    });
    const before = apiGetMock.mock.calls.filter((c: unknown[]) =>
      String(c[0]).includes('/timeline'),
    ).length;
    fireEvent.click(screen.getByTestId('coordination-timeline-window-7'));
    // Switching the window fires a fresh timeline fetch with days=7.
    await waitFor(() => {
      const sevenDayCalls = apiGetMock.mock.calls.filter((c: unknown[]) =>
        String(c[0]).includes('days=7'),
      );
      expect(sevenDayCalls.length).toBeGreaterThanOrEqual(1);
    });
    const after = apiGetMock.mock.calls.filter((c: unknown[]) =>
      String(c[0]).includes('/timeline'),
    ).length;
    expect(after).toBeGreaterThan(before);
  });

  it('renders KPI cards even when only the trade-matrix fetch fails', async () => {
    // Partial-failure regression test. Pre-fix, a single failing fan-out
    // would leave the page rendering broken skeletons (matrix was passed
    // ``data: undefined`` and stayed in its loading state forever). Now
    // the matrix panel shows its own RecoveryCard and the KPI rollup
    // renders normally.
    apiGetMock.mockImplementation((url: string) => {
      if (url.includes('/dashboard')) return Promise.resolve(DASHBOARD);
      if (url.includes('/trade-matrix'))
        return Promise.reject(new Error('matrix down'));
      if (url.includes('/timeline')) return Promise.resolve(TIMELINE);
      return Promise.reject(new Error('unexpected url'));
    });
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId('coordination-kpi-cards')).toBeInTheDocument();
    });
    expect(screen.getByTestId('coordination-matrix-error')).toBeInTheDocument();
    expect(
      screen.queryByTestId('coordination-error'),
    ).not.toBeInTheDocument();
  });
});

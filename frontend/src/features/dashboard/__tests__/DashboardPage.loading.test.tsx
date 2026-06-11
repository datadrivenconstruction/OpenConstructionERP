/**
 * FA-0005 — dashboard flash-of-empty-state regression tests.
 *
 * On a cold server the dashboard queries can stay pending for many seconds.
 * While they are PENDING the page must NOT render "0 Projects / 0 BOQs"
 * status pills or the "create your first project" welcome block — both made
 * a freshly-logged-in user believe the app lost their data. Skeletons render
 * instead, and the welcome empty-state is reserved for a SETTLED empty
 * result.
 *
 * Run:  npx vitest run src/features/dashboard/__tests__/DashboardPage.loading.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';

/* ── Scenario switch (hoisted so the vi.mock factory can read it) ─────── */

const harness = vi.hoisted(() => ({
  /**
   * 'pending'          — every query still in flight (cold server)
   * 'settled-empty'    — every query resolved; workspace genuinely empty
   * 'projects-pending' — cards settled empty, projects list still in flight
   */
  mode: 'pending' as 'pending' | 'settled-empty' | 'projects-pending',
}));

/* ── Mock @/app/i18n to prevent i18next initialization side-effects ───── */

vi.mock('@/app/i18n', () => ({
  CORE_LANGUAGES: [{ code: 'en', name: 'English', flag: 'gb', country: 'gb' }],
  EXTRA_LANGUAGES: [],
  SUPPORTED_LANGUAGES: [{ code: 'en', name: 'English', flag: 'gb', country: 'gb' }],
  getLanguageByCode: () => ({ code: 'en', name: 'English', flag: 'gb', country: 'gb' }),
  default: {
    use: () => ({ use: () => ({ use: () => ({ init: vi.fn() }) }) }),
    t: (key: string) => key,
    language: 'en',
    changeLanguage: vi.fn(),
  },
}));

/* ── Mock @tanstack/react-query — per-queryKey, scenario-driven ───────── */

vi.mock('@tanstack/react-query', () => {
  const pending = {
    data: undefined,
    isLoading: true,
    isError: false,
    isSuccess: false,
    error: null,
    refetch: vi.fn(),
  };
  const settled = (data: unknown) => ({
    data,
    isLoading: false,
    isError: false,
    isSuccess: true,
    error: null,
    refetch: vi.fn(),
  });
  // Keyed by queryKey[0]. Every dashboard queryFn settles errors to a
  // concrete fallback, so "settled" data is always a concrete value.
  const settledData: Record<string, unknown> = {
    'projects': [],
    'dashboard-project-cards': [],
    'dashboard-rollup': {},
    'me-onboarding': { completed: true },
    'modules': { modules: [] },
    'system-status': {},
    'costs': [],
    'dashboard-contacts-count': [],
    'demo-catalog': [],
  };
  return {
    useQuery: (opts: { queryKey?: unknown[] }) => {
      const root = String(opts?.queryKey?.[0] ?? '');
      if (harness.mode === 'pending') return pending;
      if (harness.mode === 'projects-pending' && root === 'projects') return pending;
      if (root in settledData) return settled(settledData[root]);
      // Queries from auxiliary widgets we don't care about here: idle.
      return { ...settled(undefined), isSuccess: false };
    },
    useMutation: () => ({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
      isError: false,
      isSuccess: false,
    }),
    useQueryClient: () => ({ invalidateQueries: vi.fn(), setQueryData: vi.fn() }),
    QueryClient: vi.fn(),
    QueryClientProvider: ({ children }: { children: React.ReactNode }) => children,
  };
});

/* ── Mock @/shared/lib/api to prevent real network calls ──────────────── */

vi.mock('@/shared/lib/api', () => ({
  API_BASE: '/api',
  getAuthToken: () => 'mock-token',
  extractErrorMessageFromBody: () => null,
  getErrorMessage: (err: unknown) => String(err),
  apiGet: vi.fn().mockResolvedValue([]),
  apiPost: vi.fn().mockResolvedValue({}),
  apiPatch: vi.fn().mockResolvedValue({}),
  apiPut: vi.fn().mockResolvedValue({}),
  apiDelete: vi.fn().mockResolvedValue(undefined),
  triggerDownload: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    statusText: string;
    body: unknown;
    constructor(status: number, statusText: string, body: unknown) {
      super(`API ${status}: ${statusText}`);
      this.name = 'ApiError';
      this.status = status;
      this.statusText = statusText;
      this.body = body;
    }
  },
}));

/* ── Mock auth store (selector-style) ─────────────────────────────────── */

const authState = {
  accessToken: 'mock-token',
  isAuthenticated: true,
  userEmail: 'test@example.com',
  userRole: 'viewer',
  setTokens: vi.fn(),
  logout: vi.fn(),
  loadFromStorage: vi.fn(),
};

vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: Object.assign(
    (selector: (s: Record<string, unknown>) => unknown) => selector(authState),
    { getState: () => authState },
  ),
}));

/* ── Helpers ──────────────────────────────────────────────────────────── */

const WELCOME_TITLE = "Welcome - let's start with your first project";

async function renderDashboard() {
  const { DashboardPage } = await import('../DashboardPage');
  return render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('oe_onboarding_completed', 'true');
});

/* ── Tests ────────────────────────────────────────────────────────────── */

describe('DashboardPage cold-server loading state (FA-0005)', () => {
  // 60s timeout: DashboardPage pulls in many lazy chunks; under full-suite
  // parallel load the default 15s is not enough (solo run takes ~4s).
  it('renders no zero counts and no welcome block while queries are pending', async () => {
    harness.mode = 'pending';
    await renderDashboard();

    // The first-project welcome CTA must NOT flash while projects load.
    expect(screen.queryByText(WELCOME_TITLE)).not.toBeInTheDocument();

    // Status pills must not claim "0 Projects / 0 BOQs" before data lands.
    expect(screen.queryByLabelText('0 Projects')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('0 BOQs')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('0 Modules')).not.toBeInTheDocument();

    // Instead the pills render in a busy/skeleton state.
    expect(screen.getByLabelText('Projects')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByLabelText('BOQs')).toHaveAttribute('aria-busy', 'true');
  }, 60000);

  it('shows skeleton rows (not the welcome block) while only the projects list is pending', async () => {
    harness.mode = 'projects-pending';
    await renderDashboard();

    expect(screen.getByTestId('dashboard-projects-loading')).toBeInTheDocument();
    expect(screen.queryByText(WELCOME_TITLE)).not.toBeInTheDocument();
    expect(screen.getByLabelText('Projects')).toHaveAttribute('aria-busy', 'true');
  }, 60000);

  it('shows the welcome block and real zero counts once queries settle empty', async () => {
    harness.mode = 'settled-empty';
    await renderDashboard();

    // A genuinely empty workspace still gets the first-project welcome CTA.
    expect(await screen.findByText(WELCOME_TITLE)).toBeInTheDocument();

    // And the status pills now show honest zeros.
    expect(screen.getByLabelText('0 Projects')).toBeInTheDocument();
    expect(screen.getByLabelText('0 BOQs')).toBeInTheDocument();
    expect(screen.queryByTestId('dashboard-projects-loading')).not.toBeInTheDocument();
  }, 60000);
});

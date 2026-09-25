// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * #412 - picking a project in the top bar left most of the dashboard
 * answering for the whole workspace.
 *
 * `GET /v1/dashboard/rollup/` accepts a `project_ids` filter and the page
 * never sent one, so every rollup-fed surface - the KPI ribbon, Finance
 * summary, the operations tiles - reported the portfolio while the Today
 * strip (which scopes itself) reported the project. On the demo estate that
 * showed as a "multi-currency" Total Value and eleven Active Estimates beside
 * a single project's name.
 *
 * The mock below serves DIFFERENT payloads for the scoped and unscoped rollup
 * keys, so the tiles can only read the scoped figures if the page actually
 * asked for them. Reverting the wiring makes the ribbon read the workspace
 * numbers again and turns these red.
 *
 * Run:  npx vitest run src/features/dashboard/__tests__/DashboardProjectScope.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import React from 'react';

// Imported here, not inside the test body. The page's module graph is large,
// and under parallel load its first import alone outran the 60 s test timeout.
// The timed-out test's render then still landed, during the next test, and that
// test failed on "Found multiple elements". Module-scope imports are paid while
// the file is collected, which no per-test timeout covers; vi.mock is hoisted
// above this line, so the page still sees every mock.
import { DashboardPage } from '../DashboardPage';

import { useProjectContextStore } from '@/stores/useProjectContextStore';

const ACTIVE_PROJECT = { id: 'p-canary', name: 'One Canary Square' };

/* ── Scenario data (hoisted so the vi.mock factory can read it) ────────── */

const harness = vi.hoisted(() => ({
  /** Every `dashboard-rollup` queryKey the page issued, in order. */
  rollupKeys: [] as unknown[][],
}));

/**
 * Two rollups that cannot be mistaken for each other:
 *   · workspace - eleven estimates, two currencies, everything priced
 *   · the one project - three estimates, one currency, three quarters priced
 * Every figure differs, so a tile reading the wrong one is unambiguous.
 */
function rollupFor(projectsCsv: string) {
  const scoped = projectsCsv === ACTIVE_PROJECT.id;
  return {
    boq_summary: scoped
      ? {
          total_boqs: 3,
          active_boqs: 3,
          total_value_eur: '27000000',
          by_currency: [{ currency: 'GBP', total_value: '27000000' }],
          multi_currency: false,
          position_count: 200,
          positions_missing_quantity: 0,
          positions_zero_price: 50,
          last_boq: null,
          by_project: [
            {
              project_id: ACTIVE_PROJECT.id,
              project_name: ACTIVE_PROJECT.name,
              boq_count: 3,
              total_value: '27000000',
              currency: 'GBP',
              position_count: 200,
              positions_missing_quantity: 0,
              positions_zero_price: 50,
            },
          ],
        }
      : {
          total_boqs: 11,
          active_boqs: 11,
          total_value_eur: '32000000',
          by_currency: [
            { currency: 'EUR', total_value: '5000000' },
            { currency: 'GBP', total_value: '27000000' },
          ],
          multi_currency: true,
          position_count: 1000,
          positions_missing_quantity: 0,
          positions_zero_price: 0,
          last_boq: null,
          by_project: [
            {
              project_id: ACTIVE_PROJECT.id,
              project_name: ACTIVE_PROJECT.name,
              boq_count: 3,
              total_value: '27000000',
              currency: 'GBP',
              position_count: 200,
              positions_missing_quantity: 0,
              positions_zero_price: 50,
            },
            {
              project_id: 'p-depot',
              project_name: 'Riverside Depot',
              boq_count: 8,
              total_value: '5000000',
              currency: 'EUR',
              position_count: 800,
              positions_missing_quantity: 0,
              positions_zero_price: 0,
            },
          ],
        },
    schedule_critical: { total_schedules: scoped ? 7 : 23, top: [] },
    // Read by FinanceSummaryCard through the rollup CONTEXT, not through the
    // page's own `useDashboardRollup` call. It is the only widget in this test
    // that proves the inner <DashboardRollupProvider projectIds={...}> is
    // wired: revert that one prop and the card falls back to "9 pending".
    change_orders: scoped
      ? {
          open_count: 2,
          by_currency: [{ currency: 'GBP', total_value: '140000' }],
        }
      : {
          open_count: 9,
          by_currency: [
            { currency: 'EUR', total_value: '310000' },
            { currency: 'GBP', total_value: '140000' },
          ],
        },
  };
}

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

/* ── Mock @tanstack/react-query - per-queryKey, scenario-driven ───────── */

vi.mock('@tanstack/react-query', () => {
  const settled = (data: unknown) => ({
    data,
    isLoading: false,
    isError: false,
    isSuccess: true,
    error: null,
    refetch: vi.fn(),
  });
  return {
    useQuery: (opts: { queryKey?: unknown[] }) => {
      const key = opts?.queryKey ?? [];
      const root = String(key[0] ?? '');
      if (root === 'dashboard-rollup') {
        harness.rollupKeys.push(key);
        return settled(rollupFor(String(key[2] ?? '')));
      }
      if (root === 'projects') return settled([]);
      if (root === 'dashboard-project-cards') return settled([]);
      if (root === 'me-onboarding') return settled({ completed: true });
      if (root === 'modules') return settled({ modules: [] });
      if (root === 'system-status') return settled({});
      if (root === 'costs') return settled([]);
      if (root === 'dashboard-contacts-count') return settled([]);
      if (root === 'demo-catalog') return settled([]);
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
  ApiError: class ApiError extends Error {},
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

async function renderRibbon() {
  render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  );
  return within(
    await screen.findByTestId('dashboard-tour-kpi-ribbon', undefined, { timeout: 20000 }),
  );
}

/** Renders the page and waits for the lazy Finance summary card to arrive. */
async function renderFinanceCard() {
  render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  );
  return screen.findByText('Open change orders', undefined, { timeout: 20000 });
}

/** The `project_ids` CSV of every rollup the page asked for. */
function requestedScopes(): string[] {
  return harness.rollupKeys.map((k) => String(k[2] ?? ''));
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('oe_onboarding_completed', 'true');
  harness.rollupKeys = [];
  useProjectContextStore.getState().clearProject();
});

/* ── Tests ────────────────────────────────────────────────────────────── */

describe('Dashboard follows the selected project (#412)', () => {
  // 60s timeout: DashboardPage pulls in many lazy chunks; under full-suite
  // parallel load the default 15s is not enough (solo run takes ~5s).
  it('asks the rollup for the project the top bar has selected', async () => {
    useProjectContextStore
      .getState()
      .setActiveProject(ACTIVE_PROJECT.id, ACTIVE_PROJECT.name);

    await renderRibbon();

    // The defect: every rollup went out with an empty project filter, so the
    // backend answered for the whole workspace.
    expect(requestedScopes()).toContain(ACTIVE_PROJECT.id);
  }, 60000);

  it('reads the project\'s estimates and schedules, not the workspace totals', async () => {
    useProjectContextStore
      .getState()
      .setActiveProject(ACTIVE_PROJECT.id, ACTIVE_PROJECT.name);

    const ribbon = await renderRibbon();

    // 3 estimates and 7 schedules belong to this project; 11 and 23 are the
    // workspace figures the tiles used to show beside its name.
    expect(ribbon.getByText('3')).toBeInTheDocument();
    expect(ribbon.getByText('7')).toBeInTheDocument();
    expect(ribbon.queryByText('11')).not.toBeInTheDocument();
    expect(ribbon.queryByText('23')).not.toBeInTheDocument();
  }, 60000);

  it('prices the project\'s own positions', async () => {
    useProjectContextStore
      .getState()
      .setActiveProject(ACTIVE_PROJECT.id, ACTIVE_PROJECT.name);

    const ribbon = await renderRibbon();

    expect(ribbon.getByText('150 of 200 priced')).toBeInTheDocument();
    // The workspace is fully priced; this project is not, and the tile used
    // to report the former.
    expect(ribbon.queryByText('100%')).not.toBeInTheDocument();
    expect(ribbon.queryByText('1000 of 1000 priced')).not.toBeInTheDocument();
  }, 60000);

  it('drops the multi-currency chip when one project is in scope', async () => {
    useProjectContextStore
      .getState()
      .setActiveProject(ACTIVE_PROJECT.id, ACTIVE_PROJECT.name);

    const ribbon = await renderRibbon();

    // A single project has a single currency. "multi-currency" beside a
    // project name was the most visible symptom of the unscoped rollup.
    expect(ribbon.queryByText('multi-currency')).not.toBeInTheDocument();
  }, 60000);

  it('scopes the widgets fed by the rollup context, not just the ribbon', async () => {
    useProjectContextStore
      .getState()
      .setActiveProject(ACTIVE_PROJECT.id, ACTIVE_PROJECT.name);

    await renderFinanceCard();

    // Finance summary reads `useDashboardRollupContext()`, so it follows the
    // provider rather than the page's own scoped query. The KPI tiles above it
    // would look right even with an unscoped provider - this is the assertion
    // that fails if the provider loses its `projectIds`.
    expect(await screen.findByText('2 pending')).toBeInTheDocument();
    expect(screen.queryByText('9 pending')).not.toBeInTheDocument();
  }, 60000);

  it('still reports the whole workspace when no project is selected', async () => {
    const ribbon = await renderRibbon();

    expect(requestedScopes().every((s) => s === '')).toBe(true);
    expect(ribbon.getByText('11')).toBeInTheDocument();
    expect(ribbon.getByText('23')).toBeInTheDocument();
    expect(ribbon.getByText('multi-currency')).toBeInTheDocument();
  }, 60000);
});

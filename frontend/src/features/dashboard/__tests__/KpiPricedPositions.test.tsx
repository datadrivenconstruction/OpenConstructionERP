// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * #187 - the "Priced positions" KPI tile read 100% when nothing was priced.
 *
 * The tile derived its percentage from ``allBoqs``, a set of stubs the page
 * synthesizes from the rollup, whose ``positions`` array held ONE entry per
 * project carrying a 0/1 flag rather than one entry per position. A project
 * with 1 priced and 99 unpriced positions therefore computed 1/1 = 100%,
 * rendered in green.
 *
 * The first test below is the one that matters: it drives the rollup with
 * exactly that shape and asserts the rendered figure. Reverting the tile to
 * read the stubs turns it red - the assertion is on what the user reads, not
 * on the helper's arithmetic, so it cannot pass while the wiring is wrong.
 *
 * Run:  npx vitest run src/features/dashboard/__tests__/KpiPricedPositions.test.tsx
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

/* ── Scenario switch (hoisted so the vi.mock factory can read it) ─────── */

const harness = vi.hoisted(() => ({
  /** ``boq_summary`` slice of the dashboard rollup for this scenario. */
  boqSummary: {} as Record<string, unknown>,
}));

/** One project, ``total`` positions of which ``zeroPriced`` carry no price. */
function summary(total: number, zeroPriced: number) {
  return {
    total_boqs: 1,
    active_boqs: 1,
    total_value_eur: '1000',
    position_count: total,
    positions_missing_quantity: 0,
    positions_zero_price: zeroPriced,
    last_boq: null,
    by_project: [
      {
        project_id: 'p1',
        project_name: 'Riverside Depot',
        boq_count: 1,
        total_value: '1000',
        currency: 'EUR',
        position_count: total,
        positions_missing_quantity: 0,
        positions_zero_price: zeroPriced,
      },
    ],
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
      const root = String(opts?.queryKey?.[0] ?? '');
      if (root === 'dashboard-rollup') {
        return settled({
          boq_summary: harness.boqSummary,
          schedule_critical: { total_schedules: 0, top: [] },
        });
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

async function renderRibbon() {
  render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  );
  // The ribbon arrives behind Suspense and a dozen lazy chunks. The default
  // 1s findBy window is enough on an idle machine and not on a loaded one,
  // and a timeout here would read as "the tile is missing" rather than "the
  // page is still mounting".
  return within(
    await screen.findByTestId('dashboard-tour-kpi-ribbon', undefined, { timeout: 20000 }),
  );
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('oe_onboarding_completed', 'true');
});

/* ── Tests ────────────────────────────────────────────────────────────── */

describe('Priced positions KPI tile (#187)', () => {
  // 60s timeout: DashboardPage pulls in many lazy chunks; under full-suite
  // parallel load the default 15s is not enough (solo run takes ~5s).
  it('reads 1% when 1 of 100 positions is priced, not 100%', async () => {
    harness.boqSummary = summary(100, 99);
    const ribbon = await renderRibbon();

    expect(ribbon.getByText('1%')).toBeInTheDocument();
    // The defect: the proxy made this tile read 100% on exactly this data.
    expect(ribbon.queryByText('100%')).not.toBeInTheDocument();
    // And the tile says what the percentage is of, so two priced positions
    // out of three cannot masquerade as a portfolio-wide reading.
    expect(ribbon.getByText('1 of 100 priced')).toBeInTheDocument();
  }, 60000);

  it('reads 0% when nothing at all is priced', async () => {
    harness.boqSummary = summary(100, 100);
    const ribbon = await renderRibbon();

    expect(ribbon.getByText('0%')).toBeInTheDocument();
    expect(ribbon.getByText('0 of 100 priced')).toBeInTheDocument();
  }, 60000);

  it('reads 100% only when every position really is priced', async () => {
    harness.boqSummary = summary(100, 0);
    const ribbon = await renderRibbon();

    expect(ribbon.getByText('100%')).toBeInTheDocument();
    expect(ribbon.getByText('100 of 100 priced')).toBeInTheDocument();
  }, 60000);

  it('states the counts, not a percentage, over a zero denominator', async () => {
    // A BOQ exists but carries no positions yet - nothing to take a
    // percentage of. Neither 0% (an accusation) nor 100% (a lie). "0 of 0
    // priced" is the truth and needs no special case: it is the same
    // sentence every other size of BOQ gets.
    harness.boqSummary = summary(0, 0);
    const ribbon = await renderRibbon();

    expect(ribbon.getByText('0 of 0 priced')).toBeInTheDocument();
    expect(ribbon.queryByText('100%')).not.toBeInTheDocument();
    expect(ribbon.queryByText('0%')).not.toBeInTheDocument();
    // The empty tile is actionable and points at the BOQ editor, which is
    // where positions get written.
    const tile = ribbon.getByText('Priced positions').closest('button');
    expect(tile).not.toBeNull();
  }, 60000);

  it('withholds the percentage on a BOQ too small to support one', async () => {
    // Three of four positions priced is "75%", which looks like a progress
    // reading on a project and is a sample of four. The counts are shown at
    // every size; the percentage is what waits for enough behind it.
    harness.boqSummary = summary(4, 1);
    const ribbon = await renderRibbon();

    expect(ribbon.getByText('3 of 4 priced')).toBeInTheDocument();
    expect(ribbon.queryByText('75%')).not.toBeInTheDocument();
    // No colour verdict either - a green tile over four positions would be
    // the same overclaim wearing a different hat. Scoped to this tile
    // rather than the ribbon, because a sibling tile may legitimately be
    // green and would answer a ribbon-wide query for it.
    //
    // `.group` and not `button`: the ribbon renders a tile as a <button>
    // only when it has an onClick, and this one has none, so `closest
    // ('button')` returned undefined and the assertion passed against
    // nothing. `.group` is on the tile root either way.
    const tile = ribbon.getByText('Priced positions').closest('.group');
    expect(tile).not.toBeNull();
    expect(tile!.querySelector('.text-semantic-success')).toBeNull();
  }, 60000);
});

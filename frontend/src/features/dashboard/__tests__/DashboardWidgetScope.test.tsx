// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * #412, second pass - the widgets the first fix did not reach.
 *
 * Scoping the rollup moved the KPI ribbon, Finance summary and the operations
 * tiles onto the selected project (see DashboardProjectScope.test.tsx). Three
 * panels kept answering for the whole workspace beside them, and all three are
 * on a fresh dashboard because nothing in the registry is hidden by default:
 *
 *   · `activity`      - the feed accepts a `project_id` and was given none.
 *   · `continue_work` - read `last_boq` off the UNSCOPED rollup, so it printed
 *                       another project's name directly under the selected one.
 *   · `portfolio`     - keyed its query on the project COUNT, which is a lossy
 *                       stand-in for identity: two different sets of the same
 *                       size share one cache entry.
 *
 * The rollup mock answers differently for the scoped and unscoped keys and the
 * fixture makes the workspace's most recent estimate belong to the OTHER
 * project - which is the real situation the report describes. Reverting any of
 * the three wirings turns these red.
 *
 * Run:  npx vitest run src/features/dashboard/__tests__/DashboardWidgetScope.test.tsx
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
const OTHER_PROJECT = { id: 'p-depot', name: 'Riverside Depot' };

/* ── Scenario data (hoisted so the vi.mock factory can read it) ────────── */

const harness = vi.hoisted(() => ({
  /** Every queryKey the page issued, in order. */
  keys: [] as unknown[][],
}));

const PROJECTS = [
  {
    id: ACTIVE_PROJECT.id,
    name: ACTIVE_PROJECT.name,
    description: '',
    region: 'GB',
    classification_standard: 'NRM',
    currency: 'GBP',
    created_at: '2026-01-04T00:00:00Z',
    address: null,
  },
  {
    id: OTHER_PROJECT.id,
    name: OTHER_PROJECT.name,
    description: '',
    region: 'DE',
    classification_standard: 'DIN276',
    currency: 'EUR',
    created_at: '2026-02-11T00:00:00Z',
    address: null,
  },
];

/**
 * The workspace's newest estimate belongs to the project that is NOT selected.
 * That is what makes "Continue your most recent estimate" print a foreign
 * project name under the selected one, and it is why an unscoped read here is
 * visible rather than merely theoretical.
 */
function rollupFor(projectsCsv: string) {
  const scoped = projectsCsv === ACTIVE_PROJECT.id;
  return {
    boq_summary: {
      total_boqs: scoped ? 3 : 11,
      active_boqs: scoped ? 3 : 11,
      total_value_eur: '0.00',
      by_currency: [],
      multi_currency: false,
      position_count: 0,
      positions_missing_quantity: 0,
      positions_zero_price: 0,
      last_boq: scoped
        ? {
            id: 'boq-canary',
            name: 'Canary fit-out estimate',
            status: 'draft',
            project_name: ACTIVE_PROJECT.name,
            position_count: 200,
            grand_total: '27000000',
            currency: 'GBP',
            updated_at: '2026-08-01T09:00:00Z',
          }
        : {
            id: 'boq-depot',
            name: 'Depot groundworks estimate',
            status: 'draft',
            project_name: OTHER_PROJECT.name,
            position_count: 800,
            grand_total: '5000000',
            currency: 'EUR',
            updated_at: '2026-08-03T09:00:00Z',
          },
      by_project: [],
    },
    schedule_critical: { total_schedules: scoped ? 7 : 23, top: [] },
    change_orders: { open_count: 0, by_currency: [] },
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

/* ── Stub the map component, keep the module ───────────────────────────
   Two projects make the `map` widget render, and it pulls maplibre through a
   WebGL canvas jsdom does not have. Nothing in this file is about the map, so
   the component is replaced rather than worked around.

   Only the component. The module also exports `resolveProjectCoords`, a pure
   helper that reads a project's explicit lat/lng, then the geocode cache, then
   a region centroid, and `DashboardSitesPanel` imports it. A whole-module mock
   listing one export makes every other export undefined, which is not a
   rendering problem the way the map is: it threw at import time and took the
   whole file down. Spreading the original keeps the helper real, so nothing
   here asserts against a coordinate this test invented. */

vi.mock('../components/DashboardProjectsMap', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../components/DashboardProjectsMap')>()),
  DashboardProjectsMap: () => <div data-testid="stub-projects-map" />,
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
      harness.keys.push(key);
      const root = String(key[0] ?? '');
      if (root === 'dashboard-rollup') return settled(rollupFor(String(key[2] ?? '')));
      if (root === 'projects') return settled(PROJECTS);
      if (root === 'activity-feed') return settled([]);
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
    useQueryClient: () => ({
      invalidateQueries: vi.fn(),
      setQueryData: vi.fn(),
      getQueryData: vi.fn(),
      removeQueries: vi.fn(),
      fetchQuery: vi.fn().mockResolvedValue(undefined),
    }),
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

async function renderDashboard() {
  render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  );
  // The "Continue your work" tile is plain (not lazy), so its presence means
  // the widget grid has rendered and every key below has been issued.
  return screen.findByTitle('Continue your work', undefined, { timeout: 20000 });
}

/** Every key the page issued whose first element is `root`. */
function keysFor(root: string): unknown[][] {
  return harness.keys.filter((k) => String(k[0] ?? '') === root);
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('oe_onboarding_completed', 'true');
  harness.keys = [];
  useProjectContextStore.getState().clearProject();
});

/* ── Tests ────────────────────────────────────────────────────────────── */

describe('Dashboard panels that stayed workspace-wide (#412)', () => {
  // 60s: DashboardPage pulls in many lazy chunks and the default 15s is not
  // enough under full-suite parallel load (solo run takes a few seconds).
  it('asks the activity feed for the selected project', async () => {
    useProjectContextStore
      .getState()
      .setActiveProject(ACTIVE_PROJECT.id, ACTIVE_PROJECT.name);

    await renderDashboard();

    // The feed carries `project_id` in both the request and its key. It was
    // mounted without the prop, so every entry in the list belonged to the
    // workspace beside widgets that answered for one project.
    const feedKeys = keysFor('activity-feed');
    expect(feedKeys.length).toBeGreaterThan(0);
    for (const key of feedKeys) {
      expect(key[1]).toBe(ACTIVE_PROJECT.id);
    }
  }, 60000);

  it('resumes the selected project\'s estimate, not the workspace\'s newest', async () => {
    useProjectContextStore
      .getState()
      .setActiveProject(ACTIVE_PROJECT.id, ACTIVE_PROJECT.name);

    const tile = within(await renderDashboard());

    // "Depot groundworks estimate" is newer, so the unscoped read picked it -
    // and printed "Riverside Depot" under the project the top bar was showing.
    expect(tile.getByText('Canary fit-out estimate')).toBeInTheDocument();
    expect(tile.queryByText('Depot groundworks estimate')).not.toBeInTheDocument();
    expect(tile.getByText(ACTIVE_PROJECT.name)).toBeInTheDocument();
    expect(tile.queryByText(OTHER_PROJECT.name)).not.toBeInTheDocument();
  }, 60000);

  it('keeps the whole workspace in the resume tile when nothing is selected', async () => {
    const tile = within(await renderDashboard());

    // Scoping must not cost the portfolio behaviour: with no project chosen
    // the scoped read IS the workspace read.
    expect(tile.getByText('Depot groundworks estimate')).toBeInTheDocument();
  }, 60000);

  it('keys the portfolio panel on nothing, so a project swap cannot serve a stale entry', async () => {
    useProjectContextStore
      .getState()
      .setActiveProject(ACTIVE_PROJECT.id, ACTIVE_PROJECT.name);

    await renderDashboard();

    // The panel is portfolio-wide on purpose, so the key carries no scope.
    // It used to carry the project COUNT, which looks like scope but is a
    // lossy hash of it: delete one project, create another, same count, same
    // cache entry, stale figures.
    const portfolioKeys = keysFor('portfolio-analytics');
    expect(portfolioKeys.length).toBeGreaterThan(0);
    for (const key of portfolioKeys) {
      expect(key).toEqual(['portfolio-analytics']);
    }
  }, 60000);
});

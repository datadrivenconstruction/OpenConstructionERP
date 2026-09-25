// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What the sidebar offers in Simple mode, with and without a company
// workspace. The rows are read as hrefs off the rendered links, in document
// order, so the order a general contractor reads the menu in is what is
// pinned, and a row that renders twice shows up as a count.
//
// The profile comes from the server (`GET /v1/users/me/onboarding/`), which is
// what lets the workspace follow the user to another browser; the tests below
// answer that call and, in some of them, disagree with the local cache on
// purpose to show which one wins. One test signs a second person in on the
// same query cache, the way a shared browser does.
//
// Which row is lit is read off the active style (`font-semibold`), since the
// sidebar, not the router, decides the one winning row.

import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, fireEvent, cleanup, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

// The suite-wide mock answers `t(key, { defaultValue: undefined })` by calling
// `.replace` on undefined, and most menu rows carry no defaultLabel. Labels
// are not what these tests read, so any string will do.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: unknown }) =>
      typeof opts?.defaultValue === 'string' ? opts.defaultValue : key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

// Surfaces around the menu that make their own calls and decide nothing here.
vi.mock('@/shared/lib/useI18nReady', () => ({ useI18nReady: () => 0 }));
vi.mock('./CustomBranding', () => ({ CustomBranding: () => null }));
vi.mock('@/shared/ui/UpdateChecker', () => ({ UpdateNotification: () => null }));
vi.mock('@/shared/ui/ArticleNewsCard', () => ({ ArticleNewsCard: () => null }));
vi.mock('@/features/modules/RequestCustomModuleDialog', () => ({
  RequestCustomModuleDialog: () => null,
}));
vi.mock('@/shared/hooks/useSidebarBadges', () => ({
  useSidebarBadges: () => ({ tasks: 0, rfi: 0, safety: 0 }),
}));
vi.mock('@/shared/hooks/useHiddenModules', () => ({
  useHiddenModules: () => ({ hiddenModules: [], setHiddenModules: vi.fn() }),
}));
vi.mock('@/features/projects/useProjectProfile', () => ({
  useActiveProjectProfile: () => ({ projectId: null, profile: undefined, isLoading: false }),
  buildModuleGate: () => ({ active: false, byRoute: () => null }),
}));

import { Sidebar } from './Sidebar';
import { meOnboardingQueryKey } from './meOnboardingQuery';
import { useAuthStore } from '@/stores/useAuthStore';
import { useModuleStore } from '@/stores/useModuleStore';
import { useViewModeStore } from '@/stores/useViewModeStore';

/** Answer the two calls the menu depends on: the backend module list (none
 *  disabled) and the signed-in user's onboarding record. */
function serverSays(companyType: string | null): void {
  api.apiGet.mockImplementation((path: string) => {
    if (path === '/v1/users/me/onboarding/') {
      return Promise.resolve({ completed: true, company_type: companyType });
    }
    return Promise.resolve([]);
  });
}

const USER_A = 'user-a';

const newClient = () => new QueryClient({ defaultOptions: { queries: { retry: false } } });

function renderWith(client: QueryClient, entry = '/') {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Sidebar />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Render at `entry`, over a cache that may already hold user A's record. */
function renderAt(entry = '/', cachedOnboarding?: unknown) {
  const client = newClient();
  if (cachedOnboarding !== undefined) client.setQueryData(meOnboardingQueryKey(USER_A), cachedOnboarding);
  return renderWith(client, entry);
}

/** An access token for a user id. Only the payload is read in the browser. */
const tokenFor = (userId: string) => `header.${btoa(JSON.stringify({ sub: userId }))}.signature`;

const nav = () => screen.getByRole('navigation', { name: 'Main navigation' });

/** Menu rows in document order. The two tiles at the foot of the list
 *  (manage modules, developer guide) are not screens and are left out. */
function menuHrefs(root: HTMLElement = nav()): string[] {
  return within(root)
    .getAllByRole('link')
    .map((a) => a.getAttribute('href') ?? '')
    .filter((href) => href !== '/modules' && href !== '/modules/developer-guide');
}

/** The rows drawn as the current screen. */
const litHrefs = (): string[] =>
  within(nav())
    .getAllByRole('link')
    .filter((a) => a.className.includes('font-semibold'))
    .map((a) => a.getAttribute('href') ?? '');

const moreExpanded = () => screen.getByTestId('sidebar-more-modules').getAttribute('aria-expanded');

// The Learn card (Videos, Cases) sits above everything else in every mode,
// workspace included, until the user hides it.
const LEARN = ['/videos', '/cases'];

const GC_WORKSPACE = [
  '/',
  '/inbox',
  '/projects',
  '/boq',
  '/finance?tab=budgets',
  '/contracts',
  '/subcontractors',
  '/changeorders',
  '/contracts?tab=claims',
  '/finance?tab=payments',
  '/finance?tab=retention',
  '/schedule',
  '/daily-diary',
  '/punchlist',
  '/closeout',
];

// Simple mode as it has always been: the groups without `hideInSimple`, minus
// their `advancedOnly` rows. Written out rather than derived from the catalogue,
// because deriving it would restate the rule under test.
const TODAYS_SIMPLE = [
  ...LEARN,
  '/',
  '/projects',
  '/files',
  '/inbox',
  '/timeline',
  '/takeoff?tab=measurements',
  '/dwg-takeoff',
  '/bim',
  '/quantities',
  '/costs',
  '/catalog',
  '/cost-explorer',
  '/assemblies',
  '/cost-match',
  '/fx',
  '/boq',
  '/templates',
  '/regional-exchange',
  '/match-elements',
  '/project-intelligence',
  '/rom-estimate',
  '/methodologies',
  '/sheets',
  '/geo',
  '/pointcloud',
  '/contracts',
  '/payment-clock',
  '/tax-withholding',
  '/tax-rates',
  '/einvoice-clearance',
];

beforeEach(() => {
  localStorage.clear();
  api.apiGet.mockReset();
  useAuthStore.setState({ isAuthenticated: true, userRole: 'editor', userId: USER_A, accessToken: null });
  // Every module on, so the rows below depend on the mode and the profile only.
  useModuleStore.setState({ enabledModules: {}, hiddenGroups: [] });
  // The store reads localStorage once at import, so the mode is set on it.
  useViewModeStore.getState().setMode('simple');
});

afterEach(() => cleanup());

describe('Simple mode with a general contractor profile', () => {
  it('shows the workspace rows, in order, and nothing else until More modules opens', async () => {
    serverSays('general_contractor');
    renderAt('/');

    const workspace = await screen.findByTestId('sidebar-workspace');
    expect(menuHrefs(workspace)).toEqual(GC_WORKSPACE);
    expect(menuHrefs()).toEqual([...LEARN, ...GC_WORKSPACE]);
    expect(screen.getByText('General Contractor')).toBeTruthy();

    const more = screen.getByTestId('sidebar-more-modules');
    expect(more.getAttribute('aria-expanded')).toBe('false');
  });

  it('reveals every other screen under More modules without listing a workspace row twice', async () => {
    serverSays('general_contractor');
    renderAt('/');

    fireEvent.click(await screen.findByTestId('sidebar-more-modules'));

    const hrefs = menuHrefs();
    expect(hrefs.slice(0, LEARN.length + GC_WORKSPACE.length)).toEqual([...LEARN, ...GC_WORKSPACE]);
    // Screens Simple mode hid outright are now one click away...
    for (const route of ['/rfi', '/finance', '/variations', '/fx', '/geo', '/crm']) {
      expect(hrefs).toContain(route);
    }
    // ...and the workspace's own rows appear once, in the workspace.
    for (const route of GC_WORKSPACE) {
      expect(hrefs.filter((href) => href === route)).toHaveLength(1);
    }
    expect(screen.getByTestId('sidebar-more-modules').getAttribute('aria-expanded')).toBe('true');
  });

  it('lights the tab row a link opens, not the row of its page', async () => {
    serverSays('general_contractor');
    renderAt('/contracts?tab=claims');

    const workspace = await screen.findByTestId('sidebar-workspace');
    const link = (href: string) =>
      within(workspace)
        .getAllByRole('link')
        .find((a) => a.getAttribute('href') === href)!;
    await waitFor(() => expect(link('/contracts?tab=claims').className).toContain('font-semibold'));
    expect(link('/contracts').className).not.toContain('font-semibold');
  });

  it('opens More modules by itself when the current screen lives there', async () => {
    serverSays('general_contractor');
    renderAt('/rfi');

    const more = await screen.findByTestId('sidebar-more-modules');
    await waitFor(() => expect(more.getAttribute('aria-expanded')).toBe('true'));
    expect(menuHrefs()).toContain('/rfi');
  });

  it('follows the server, not the cache of whoever used this browser before', async () => {
    localStorage.setItem('oe_company_type', 'general_contractor');
    serverSays('estimator');
    renderAt('/');

    await waitFor(() => expect(screen.queryByTestId('sidebar-workspace')).toBeNull());
    expect(menuHrefs()).toEqual(TODAYS_SIMPLE);
    expect(localStorage.getItem('oe_company_type')).toBe('estimator');
  });

  it('asks again when the menu mounts, so a profile saved in another browser shows', async () => {
    // This user's record is fresh in the cache, but out of date.
    serverSays('estimator');
    renderAt('/', { completed: true, company_type: 'general_contractor' });

    await waitFor(() => expect(screen.queryByTestId('sidebar-workspace')).toBeNull());
    expect(menuHrefs()).toEqual(TODAYS_SIMPLE);
  });

  it('drops a cached profile the server does not have', async () => {
    localStorage.setItem('oe_company_type', 'general_contractor');
    serverSays(null);
    renderAt('/');

    await waitFor(() => expect(localStorage.getItem('oe_company_type')).toBeNull());
    expect(screen.queryByTestId('sidebar-workspace')).toBeNull();
    expect(menuHrefs()).toEqual(TODAYS_SIMPLE);
  });

  it('reaches a browser the wizard never ran in', async () => {
    serverSays('general_contractor');
    renderAt('/');

    expect(menuHrefs(await screen.findByTestId('sidebar-workspace'))).toEqual(GC_WORKSPACE);
    expect(localStorage.getItem('oe_company_type')).toBe('general_contractor');
  });
});

describe('on a browser two people share', () => {
  it('shows the next person nothing of the previous workspace, even before the server answers', async () => {
    // One tab, one query cache, as in the app: signing out keeps the cache.
    const client = newClient();

    // A, a general contractor, signs in and gets the workspace.
    useAuthStore.getState().setTokens(tokenFor(USER_A), 'refresh-a', true, 'a@example.com');
    serverSays('general_contractor');
    const first = renderWith(client, '/');
    expect(menuHrefs(await screen.findByTestId('sidebar-workspace'))).toEqual(GC_WORKSPACE);
    expect(localStorage.getItem('oe_company_type')).toBe('general_contractor');

    // A signs out. The menu goes with the layout; A's record stays cached.
    first.unmount();
    useAuthStore.getState().logout();
    expect(localStorage.getItem('oe_company_type')).toBeNull();
    expect(client.getQueryData(meOnboardingQueryKey(USER_A))).toMatchObject({
      company_type: 'general_contractor',
    });

    // B signs in on the same tab and has no profile. Hold the server's answer
    // back: the first paint must already be B's menu, not A's.
    let answer: (record: unknown) => void = () => undefined;
    api.apiGet.mockReset();
    api.apiGet.mockImplementation((path: string) =>
      path === '/v1/users/me/onboarding/'
        ? new Promise((resolve) => {
            answer = resolve;
          })
        : Promise.resolve([]),
    );
    useAuthStore.getState().setTokens(tokenFor('user-b'), 'refresh-b', true, 'b@example.com');
    renderWith(client, '/');

    await waitFor(() => expect(api.apiGet).toHaveBeenCalledWith('/v1/users/me/onboarding/'));
    expect(screen.queryByTestId('sidebar-workspace')).toBeNull();
    expect(menuHrefs()).toEqual(TODAYS_SIMPLE);

    await act(async () => answer({ completed: true, company_type: null }));
    expect(screen.queryByTestId('sidebar-workspace')).toBeNull();
    expect(menuHrefs()).toEqual(TODAYS_SIMPLE);
    expect(client.getQueryData(meOnboardingQueryKey('user-b'))).toMatchObject({ company_type: null });
  });
});

describe('which row is lit', () => {
  it('lights Dashboard on /dashboard, where / redirects', async () => {
    serverSays('general_contractor');
    renderAt('/dashboard');

    await screen.findByTestId('sidebar-workspace');
    await waitFor(() => expect(litHrefs()).toEqual(['/']));
    expect(moreExpanded()).toBe('false');
  });

  it('lights Dashboard on /dashboard in Advanced mode too, and not on /dashboards', async () => {
    useViewModeStore.getState().setMode('advanced');
    serverSays(null);
    renderAt('/dashboard');
    await waitFor(() => expect(litHrefs()).toEqual(['/']));
    cleanup();
    api.apiGet.mockClear();

    renderAt('/dashboards');
    await waitFor(() => expect(api.apiGet).toHaveBeenCalledWith('/v1/users/me/onboarding/'));
    expect(litHrefs()).not.toContain('/');
  });

  it('lights Budgets on plain /finance, which opens on that tab, and leaves More modules shut', async () => {
    serverSays('general_contractor');
    renderAt('/finance');

    await screen.findByTestId('sidebar-workspace');
    await waitFor(() => expect(litHrefs()).toEqual(['/finance?tab=budgets']));
    expect(moreExpanded()).toBe('false');
  });

  it('lights Budgets for a tab Finance does not have, since Finance shows Budgets then', async () => {
    serverSays('general_contractor');
    renderAt('/finance?tab=no-such-tab');

    await screen.findByTestId('sidebar-workspace');
    await waitFor(() => expect(litHrefs()).toEqual(['/finance?tab=budgets']));
  });

  it('opens More modules on a Finance tab that is not in the workspace and lights Finance there', async () => {
    serverSays('general_contractor');
    renderAt('/finance?tab=invoices');

    await screen.findByTestId('sidebar-workspace');
    await waitFor(() => expect(moreExpanded()).toBe('true'));
    expect(litHrefs()).toEqual(['/finance']);
  });

  it('keeps plain /contracts on the Contracts row, not on the claims tab', async () => {
    serverSays('general_contractor');
    renderAt('/contracts');

    await screen.findByTestId('sidebar-workspace');
    await waitFor(() => expect(litHrefs()).toEqual(['/contracts']));
    expect(moreExpanded()).toBe('false');
  });
});

describe('without a workspace, or in Advanced mode', () => {
  it('Simple mode for a profile with no workspace is what it always was', async () => {
    serverSays('estimator');
    renderAt('/');

    await waitFor(() => expect(api.apiGet).toHaveBeenCalledWith('/v1/users/me/onboarding/'));
    expect(screen.queryByTestId('sidebar-workspace')).toBeNull();
    expect(screen.queryByTestId('sidebar-more-modules')).toBeNull();
    expect(menuHrefs()).toEqual(TODAYS_SIMPLE);
  });

  it('Simple mode with no profile at all is what it always was', async () => {
    serverSays(null);
    renderAt('/');

    await waitFor(() => expect(api.apiGet).toHaveBeenCalledWith('/v1/users/me/onboarding/'));
    expect(menuHrefs()).toEqual(TODAYS_SIMPLE);
  });

  it('Advanced mode ignores the workspace and shows the whole catalogue', async () => {
    useViewModeStore.getState().setMode('advanced');
    serverSays('general_contractor');
    renderAt('/');

    await waitFor(() => expect(api.apiGet).toHaveBeenCalledWith('/v1/users/me/onboarding/'));
    expect(screen.queryByTestId('sidebar-workspace')).toBeNull();
    expect(screen.queryByTestId('sidebar-more-modules')).toBeNull();
    const hrefs = menuHrefs();
    expect(hrefs.slice(0, 7)).toEqual([...LEARN, '/', '/projects', '/files', '/inbox', '/timeline']);
    for (const route of ['/subcontractors', '/changeorders', '/finance', '/fx', '/geo']) {
      expect(hrefs).toContain(route);
    }
    expect(hrefs).not.toContain('/finance?tab=budgets');
  });
});

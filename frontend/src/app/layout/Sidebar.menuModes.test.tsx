// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
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
vi.mock('@/shared/ui/UpdateChecker', () => ({ UpdateNotification: () => null, UpdateBadge: () => null }));
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


import { useMenuLayoutStore } from './useMenuLayoutStore';
import { DEFAULT_MODE_ITEMS } from './menuLayout';

function renderSidebar(entry = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Sidebar />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const nav = () => screen.getByRole('navigation', { name: 'Main navigation' });

describe('sidebar work modes', () => {
  beforeEach(() => {
    localStorage.clear();
    serverSays(null);
    useAuthStore.setState({ isAuthenticated: true, userRole: 'admin' } as never);
    useModuleStore.setState({ hiddenGroups: [] } as never);
    useViewModeStore.setState({ mode: 'advanced' } as never);
    act(() => useMenuLayoutStore.getState().dispatch({ type: 'reset' }));
    act(() => useMenuLayoutStore.getState().dispatch({ type: 'setMode', mode: 'all' }));
  });
  afterEach(() => cleanup());

  it('switching to Site manager shows only its rows, and More opens the rest', async () => {
    renderSidebar();
    fireEvent.change(screen.getByTestId('menu-mode-select'), { target: { value: 'site_manager' } });
    const mode = await screen.findByTestId('sidebar-mode');
    const hrefs = within(mode).getAllByRole('link').map((a) => a.getAttribute('href'));
    expect(hrefs.length).toBeGreaterThanOrEqual(8);
    for (const h of hrefs) expect(DEFAULT_MODE_ITEMS.site_manager).toContain(h);
    expect(within(nav()).getAllByRole('link').map((a) => a.getAttribute('href'))).not.toContain('/boq');
    fireEvent.click(screen.getByTestId('sidebar-more-modules'));
    await waitFor(() => expect(within(nav()).getAllByRole('link').length).toBeGreaterThan(hrefs.length + 20));
  });

  it('a user group renders its rows at the top, and reset removes it', async () => {
    act(() => {
      const { dispatch } = useMenuLayoutStore.getState();
      dispatch({ type: 'addUserGroup', id: 'day', label: 'My day' });
      dispatch({ type: 'toggleUserGroupItem', id: 'day', route: '/rfi' });
    });
    renderSidebar();
    const group = await screen.findByTestId('sidebar-user-group');
    expect(within(group).getAllByRole('link').map((a) => a.getAttribute('href'))).toEqual(['/rfi']);
    act(() => useMenuLayoutStore.getState().dispatch({ type: 'reset' }));
    await waitFor(() => expect(screen.queryByTestId('sidebar-user-group')).toBeNull());
  });

  it('the arrange dialog opens with Reset to default', async () => {
    renderSidebar();
    fireEvent.click(screen.getByTestId('menu-arrange'));
    expect(await screen.findByTestId('menu-organizer')).toBeTruthy();
    expect(screen.getByTestId('menu-layout-reset')).toBeTruthy();
  });
});

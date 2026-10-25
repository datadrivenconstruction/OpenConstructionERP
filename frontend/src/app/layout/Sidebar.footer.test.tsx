// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The footer of the sidebar: every button is there by default, a hidden one is
// gone at once, and with nothing optional left only the version line stays.

import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));
const hidden = vi.hoisted(() => ({ list: [] as string[] }));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: unknown }) =>
      typeof opts?.defaultValue === 'string' ? opts.defaultValue : key,
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

vi.mock('@/shared/lib/useI18nReady', () => ({ useI18nReady: () => 0 }));
vi.mock('./CustomBranding', () => ({ CustomBranding: () => null }));
vi.mock('@/shared/ui/UpdateChecker', () => ({
  UpdateNotification: () => null,
  UpdateBadge: () => null,
}));
vi.mock('@/features/modules/RequestCustomModuleDialog', () => ({
  RequestCustomModuleDialog: () => null,
}));
vi.mock('@/shared/hooks/useSidebarBadges', () => ({
  useSidebarBadges: () => ({ tasks: 0, rfi: 0, safety: 0 }),
}));
vi.mock('@/shared/hooks/useHiddenModules', () => ({
  useHiddenModules: () => ({ hiddenModules: hidden.list, setHiddenModules: vi.fn(), isLoading: false }),
}));
vi.mock('@/features/projects/useProjectProfile', () => ({
  useActiveProjectProfile: () => ({ projectId: null, profile: undefined, isLoading: false }),
  buildModuleGate: () => ({ active: false, byRoute: () => null }),
}));

import { Sidebar } from './Sidebar';
import { useAuthStore } from '@/stores/useAuthStore';
import { useModuleStore } from '@/stores/useModuleStore';
import { useViewModeStore } from '@/stores/useViewModeStore';
import { useSidebarCollapseStore } from '@/stores/useSidebarCollapseStore';
import { DEFAULT_FOOTER_PREFS, resetFooterPrefsCache, writeFooterPrefs } from '@/shared/lib/footerPrefs';

function renderSidebar() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <Sidebar />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// The mocked `t` returns the key where no default is given, so the route tiles
// are found by key. Tiles are looked up inside the footer grid only: the menu
// also has its own "Edit menu" button under the module list.
const TILE: Record<string, string> = {
  Settings: 'sidebar.admin_grid.settings',
  Users: 'sidebar.admin_grid.users',
  About: 'sidebar.admin_grid.about',
  'Edit menu': 'sidebar.edit_menu',
};
const button = (name: string) =>
  Array.from(document.querySelectorAll('ul.grid-cols-2 button')).find(
    (b) => b.getAttribute('aria-label') === (TILE[name] ?? name),
  ) ?? null;
const link = (name: string) => screen.queryByRole('link', { name });

beforeEach(() => {
  localStorage.clear();
  hidden.list = [];
  resetFooterPrefsCache();
  api.apiGet.mockReset();
  api.apiGet.mockImplementation((path: string) =>
    path === '/v1/users/me/onboarding/'
      ? Promise.resolve({ completed: true, company_type: null })
      : Promise.resolve([]),
  );
  useAuthStore.setState({ isAuthenticated: true, userRole: 'editor', userId: 'user-a', accessToken: null });
  useModuleStore.setState({ enabledModules: {}, hiddenGroups: [] });
  useViewModeStore.getState().setMode('simple');
  useSidebarCollapseStore.getState().setIconified(false);
});

afterEach(() => cleanup());

describe('the sidebar footer', () => {
  it('shows every button by default', () => {
    renderSidebar();
    expect(button('Settings')).not.toBeNull();
    expect(button('Users')).not.toBeNull();
    expect(button('Edit menu')).not.toBeNull();
    expect(button('About')).not.toBeNull();
    expect(link('GitHub repository')).not.toBeNull();
    expect(link('Telegram community')).not.toBeNull();
    expect(screen.getByText(/^v\d/)).toBeTruthy();
  });

  it('drops Edit menu and GitHub the moment they are switched off', () => {
    renderSidebar();
    act(() => writeFooterPrefs({ ...DEFAULT_FOOTER_PREFS, editMenu: true, github: true }));
    expect(button('Edit menu')).toBeNull();
    expect(link('GitHub repository')).toBeNull();
    expect(link('Telegram community')).not.toBeNull();
    // The other tiles are untouched.
    expect(button('Settings')).not.toBeNull();
    expect(button('About')).not.toBeNull();
  });

  it('drops Settings, Users and About through the per-user hidden list', () => {
    hidden.list = ['/settings', '/users', '/about'];
    renderSidebar();
    expect(button('Settings')).toBeNull();
    expect(button('Users')).toBeNull();
    expect(button('About')).toBeNull();
    expect(button('Edit menu')).not.toBeNull();
  });

  it('collapses cleanly when everything optional is hidden: no tiles, no empty grid, version stays', () => {
    hidden.list = ['/settings', '/users', '/about'];
    writeFooterPrefs({ editMenu: true, github: true, community: true });
    const { container } = renderSidebar();
    expect(button('Settings')).toBeNull();
    expect(button('Edit menu')).toBeNull();
    expect(link('GitHub repository')).toBeNull();
    expect(link('Telegram community')).toBeNull();
    expect(container.querySelectorAll('ul.grid-cols-2')).toHaveLength(0);
    expect(container.querySelectorAll('div.grid-cols-2')).toHaveLength(0);
    expect(screen.getByText(/^v\d/)).toBeTruthy();
    expect(screen.getByText('AGPL-3.0')).toBeTruthy();
  });

  it('collapses the icon-only footer too', () => {
    useSidebarCollapseStore.getState().setIconified(true);
    renderSidebar();
    expect(link('GitHub repository')).not.toBeNull();
    act(() => writeFooterPrefs({ editMenu: false, github: true, community: true }));
    expect(link('GitHub repository')).toBeNull();
    expect(link('Telegram community')).toBeNull();
  });
});

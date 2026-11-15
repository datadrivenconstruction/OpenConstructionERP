// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The AI chat stays in its thematic group, groups carry no captions, and an open
// demo shows only the modules its cards cover.
import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, cleanup, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));
const demo = vi.hoisted(() => ({ modules: null as readonly string[] | null }));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});
vi.mock('@/shared/lib/useDemoModules', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/useDemoModules')>('@/shared/lib/useDemoModules');
  return { ...actual, useDemoModules: () => demo.modules };
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
import { useMenuLayoutStore } from './useMenuLayoutStore';
import { DEMO_ALWAYS_ROUTES } from '@/shared/lib/useDemoModules';
import { navGroups } from './navCatalog';

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

const nav = () => screen.getByRole('navigation', { name: 'Main navigation' });
const hrefs = () => within(nav()).getAllByRole('link').map((a) => a.getAttribute('href'));

describe('sidebar structure and demo menu', () => {
  beforeEach(() => {
    localStorage.clear();
    demo.modules = null;
    api.apiGet.mockImplementation((path: string) =>
      Promise.resolve(path === '/v1/users/me/onboarding/' ? { completed: true, company_type: null } : []),
    );
    useAuthStore.setState({ isAuthenticated: true, userRole: 'admin' } as never);
    useModuleStore.setState({ hiddenGroups: [] } as never);
    useViewModeStore.setState({ mode: 'advanced' } as never);
    act(() => useMenuLayoutStore.getState().dispatch({ type: 'reset' }));
    act(() => useMenuLayoutStore.getState().dispatch({ type: 'setMode', mode: 'all' }));
  });
  afterEach(() => cleanup());

  it('keeps the AI chat in Automation & AI, with no entry of its own on top', async () => {
    // The rendered rows depend on installed packages, so the placement is read from the catalog.
    const ai = navGroups.find((g) => g.id === 'grp_automation_ai');
    expect(ai?.items.map((i) => i.to)).toContain('/chat');
    expect(navGroups.flatMap((g) => g.items).filter((i) => i.to === '/chat')).toHaveLength(1);
    renderSidebar();
    await waitFor(() => expect(hrefs()).toContain('/boq'));
    expect(screen.queryByTestId('sidebar-assistant')).toBeNull();
    const all = hrefs();
    expect(all.filter((h) => h === '/chat').length).toBeLessThanOrEqual(1);
    if (all.includes('/chat')) expect(all.indexOf('/chat')).toBeGreaterThan(all.indexOf('/boq'));
  });

  it('draws groups without section captions', async () => {
    const view = renderSidebar();
    await waitFor(() => expect(hrefs()).toContain('/boq'));
    expect(view.container.querySelector('[data-testid^="sidebar-section-"]')).toBeNull();
  });

  it('shows only the modules the open demo covers', async () => {
    // Takeoff and Estimating are open by default; collapsed groups render no links.
    demo.modules = ['/boq', '/dwg-takeoff'];
    renderSidebar();
    await waitFor(() => expect(hrefs()).toContain('/boq'));
    const shown = hrefs();
    expect(shown).not.toContain('/chat');
    for (const route of ['/', '/projects', '/boq', '/dwg-takeoff']) expect(shown).toContain(route);
    const catalogue = new Set(navGroups.flatMap((g) => g.items.map((i) => i.to)));
    for (const route of shown.filter((r) => catalogue.has(r!))) {
      expect(DEMO_ALWAYS_ROUTES.has(route!) || ['/boq', '/dwg-takeoff'].includes(route!), route!).toBe(true);
    }
  });

  it('keeps a group made in this browser out of a demo menu', async () => {
    act(() => {
      const { dispatch } = useMenuLayoutStore.getState();
      dispatch({ type: 'addUserGroup', id: 'test', label: 'test' });
      dispatch({ type: 'toggleUserGroupItem', id: 'test', route: '/chat' });
    });
    demo.modules = ['/boq'];
    const view = renderSidebar();
    await waitFor(() => expect(hrefs()).toContain('/boq'));
    expect(screen.queryByTestId('sidebar-user-group')).toBeNull();
    view.unmount();
    demo.modules = null;
    renderSidebar();
    await waitFor(() => expect(screen.getByTestId('sidebar-user-group')).toBeTruthy());
  });
});

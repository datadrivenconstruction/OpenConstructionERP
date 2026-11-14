// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The assistant is one entry under the Learn card, long groups are read by captions, and
// an open demo shows only the modules its cards cover.
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

  it('puts the AI chat in one assistant entry under Learn, not a section', async () => {
    renderSidebar();
    const assistant = await screen.findByTestId('sidebar-assistant');
    expect(within(assistant).getAllByRole('link').map((a) => a.getAttribute('href'))).toEqual(['/chat']);
    // Right under the Learn card, before any working group.
    const all = hrefs();
    expect(all.indexOf('/chat')).toBe(all.indexOf('/packs') + 1);
    expect(hrefs().filter((h) => h === '/chat')).toHaveLength(1);
  });

  it('reads a long group by its section captions', async () => {
    renderSidebar();
    expect(await screen.findByTestId('sidebar-section-takeoff')).toBeTruthy();
    expect(screen.getByTestId('sidebar-section-boq')).toBeTruthy();
  });

  it('drops a caption that would only repeat its group header', async () => {
    useViewModeStore.setState({ mode: 'simple' } as never);
    renderSidebar();
    await screen.findByTestId('sidebar-assistant');
    // In Simple mode Cost Data shows only its databases, so no caption.
    expect(hrefs()).toContain('/costs');
    expect(screen.queryByTestId('sidebar-section-databases')).toBeNull();
  });

  it('shows only the modules the open demo covers', async () => {
    // Both rows sit in Estimating, which is open by default; collapsed groups render no links.
    demo.modules = ['/boq', '/dwg-takeoff'];
    renderSidebar();
    await screen.findByTestId('sidebar-assistant');
    const shown = hrefs();
    for (const route of ['/chat', '/', '/projects', '/boq', '/dwg-takeoff']) expect(shown).toContain(route);
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
    await screen.findByTestId('sidebar-assistant');
    expect(screen.queryByTestId('sidebar-user-group')).toBeNull();
    view.unmount();
    demo.modules = null;
    renderSidebar();
    await waitFor(() => expect(screen.getByTestId('sidebar-user-group')).toBeTruthy());
  });
});

// Design module (ERP side of the design editor link).
// Patch 0012: a person who picked a company profile and said yes to Design finds Design in the menu,
// next to the profile's workspace, not folded under "More modules".
import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPatch: vi.fn(), apiDelete: vi.fn() }));
vi.mock('@/shared/lib/api', async () => ({ ...(await vi.importActual<object>('@/shared/lib/api')), ...api }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: unknown }) => (typeof opts?.defaultValue === 'string' ? opts.defaultValue : key),
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));
vi.mock('@/shared/lib/useI18nReady', () => ({ useI18nReady: () => 0 }));
vi.mock('@/app/layout/CustomBranding', () => ({ CustomBranding: () => null }));
vi.mock('@/shared/ui/UpdateChecker', () => ({ UpdateNotification: () => null, UpdateBadge: () => null }));
vi.mock('@/features/modules/RequestCustomModuleDialog', () => ({ RequestCustomModuleDialog: () => null }));
vi.mock('@/shared/hooks/useSidebarBadges', () => ({ useSidebarBadges: () => ({ tasks: 0, rfi: 0, safety: 0 }) }));
vi.mock('@/shared/hooks/useHiddenModules', () => ({ useHiddenModules: () => ({ hiddenModules: [], setHiddenModules: vi.fn() }) }));
vi.mock('@/features/projects/useProjectProfile', () => ({
  useActiveProjectProfile: () => ({ projectId: null, profile: undefined, isLoading: false }),
  buildModuleGate: () => ({ active: false, byRoute: () => null }),
}));

import { Sidebar } from '@/app/layout/Sidebar';
import { useAuthStore } from '@/stores/useAuthStore';
import { useModuleStore } from '@/stores/useModuleStore';
import { useViewModeStore } from '@/stores/useViewModeStore';

function mount(design: boolean) {
  api.apiGet.mockImplementation((path: string) =>
    Promise.resolve(path === '/v1/users/me/onboarding/' ? { completed: true, company_type: 'general_contractor' } : []));
  useModuleStore.setState({ enabledModules: { design }, hiddenGroups: [] });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/']}><Sidebar /></MemoryRouter>
    </QueryClientProvider>,
  );
}
const nav = () => screen.getByRole('navigation', { name: 'Main navigation' });
const designLinks = () => within(nav()).queryAllByRole('link').filter((a) => (a.getAttribute('href') ?? '').startsWith('/design/'));

beforeEach(() => {
  localStorage.clear();
  api.apiGet.mockReset();
  useAuthStore.setState({ isAuthenticated: true, userRole: 'editor', userId: 'user-a', accessToken: null });
  useViewModeStore.getState().setMode('simple');
});
afterEach(() => cleanup());

describe('Design beside a company workspace', () => {
  it('stays in view with "More modules" closed, and is not listed twice when it opens', async () => {
    mount(true);
    await screen.findByTestId('sidebar-workspace');
    expect(screen.getByTestId('sidebar-more-modules').getAttribute('aria-expanded')).toBe('false');
    await waitFor(() => expect(designLinks().length).toBeGreaterThanOrEqual(5));
    const before = designLinks().length;
    fireEvent.click(screen.getByTestId('sidebar-more-modules'));
    expect(designLinks().length).toBe(before);
  });

  it('is not there while the module is off', async () => {
    mount(false);
    await screen.findByTestId('sidebar-workspace');
    fireEvent.click(screen.getByTestId('sidebar-more-modules'));
    expect(designLinks()).toHaveLength(0);
  });
});

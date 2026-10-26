// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pinned menu rows: pinned order is kept, and in the menu editor a row moves up
// or down.

import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, act, fireEvent } from '@testing-library/react';
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

const pinnedOrder = () => {
  const section = screen.getByText('Pinned').closest('div.mb-2')!;
  return Array.from(section.querySelectorAll('ul > li a')).map((a) => a.getAttribute('href'));
};

const openEditor = () =>
  act(() => {
    fireEvent.click(screen.getAllByRole('button', { name: /Edit menu/ })[0]!);
  });

beforeEach(() => {
  localStorage.clear();
  hidden.list = [];
  api.apiGet.mockReset();
  api.apiGet.mockImplementation((path: string) =>
    path === '/v1/users/me/onboarding/'
      ? Promise.resolve({ completed: true, company_type: null })
      : Promise.resolve([]),
  );
  useAuthStore.setState({ isAuthenticated: true, userRole: 'editor', userId: 'user-a', accessToken: null });
  useModuleStore.setState({ enabledModules: {}, hiddenGroups: [] });
  useViewModeStore.getState().setMode('advanced');
  useSidebarCollapseStore.getState().setIconified(false);
  localStorage.setItem('oce-pinned-routes', JSON.stringify(['/boq', '/tasks', '/schedule']));
});

afterEach(() => cleanup());

// The mocked `t` does not interpolate, so every reorder button carries the template text.
const UP = 'Move {{item}} up';
const DOWN = 'Move {{item}} down';

describe('pinned menu rows', () => {
  it('lists the pinned rows in their stored order with no reorder buttons outside the editor', () => {
    renderSidebar();
    expect(pinnedOrder()).toEqual(['/boq', '/tasks', '/schedule']);
    expect(screen.queryByTestId('pinned-reorder')).toBeNull();
  });

  it('moves a pinned row down and up in the editor and keeps the order', () => {
    renderSidebar();
    openEditor();
    fireEvent.click(screen.getAllByRole('button', { name: DOWN })[0]!);
    expect(pinnedOrder()).toEqual(['/tasks', '/boq', '/schedule']);
    expect(JSON.parse(localStorage.getItem('oce-pinned-routes')!)).toEqual(['/tasks', '/boq', '/schedule']);
    fireEvent.click(screen.getAllByRole('button', { name: UP })[2]!);
    expect(pinnedOrder()).toEqual(['/tasks', '/schedule', '/boq']);
  });

  it('cannot move the first row up or the last row down', () => {
    renderSidebar();
    openEditor();
    const ups = screen.getAllByRole('button', { name: UP }) as HTMLButtonElement[];
    const downs = screen.getAllByRole('button', { name: DOWN }) as HTMLButtonElement[];
    expect(ups[0]!.disabled).toBe(true);
    expect(downs[downs.length - 1]!.disabled).toBe(true);
  });
});

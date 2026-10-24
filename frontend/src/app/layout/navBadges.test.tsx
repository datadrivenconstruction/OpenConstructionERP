// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';

const apiGet = vi.fn();
vi.mock('@/shared/lib/api', () => ({ apiGet: (...a: unknown[]) => apiGet(...a) }));

import {
  NavItemBadge,
  NAV_BADGE_POLL_MS,
  badgeText,
  navBadgesQueryKey,
  useNavBadges,
  useNavItemShortcut,
} from './navBadges';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { registerAppActions } from '@/app/actions/coreActions';

function wrap() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <MemoryRouter>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </MemoryRouter>
  );
}

beforeEach(() => {
  apiGet.mockReset();
  useAuthStore.setState({ isAuthenticated: true, accessToken: 'tok' } as never);
  useProjectContextStore.setState({ activeProjectId: null, activeProjectName: '' });
});

describe('nav badges', () => {
  it('asks once for every badge, scoped to the active project', async () => {
    useProjectContextStore.setState({ activeProjectId: 'p 1', activeProjectName: 'Berlin' });
    apiGet.mockResolvedValue({ project_id: 'p 1', badges: { '/finance': { count: 3, kind: 'awaiting', tone: 'warning' } } });
    const Wrapper = wrap();
    render(
      <Wrapper>
        <NavItemBadge itemId="/finance" />
        <NavItemBadge itemId="/issues" />
      </Wrapper>,
    );
    const badge = await screen.findByTestId('nav-badge-/finance');
    expect(badge.textContent).toBe('3');
    expect(badge.getAttribute('aria-label')).toBe('Awaiting approval: 3');
    expect(screen.queryByTestId('nav-badge-/issues')).toBeNull();
    expect(apiGet).toHaveBeenCalledTimes(1);
    expect(apiGet).toHaveBeenCalledWith('/v1/dashboard/nav-badges/?project_id=p%201');
  });

  it('polls once a minute and not while the tab is hidden', () => {
    apiGet.mockResolvedValue({ project_id: null, badges: {} });
    const client = new QueryClient();
    renderHook(() => useNavBadges(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    });
    const query = client.getQueryCache().find({ queryKey: navBadgesQueryKey(null) });
    const options = query?.observers[0]?.options;
    expect(options?.refetchInterval).toBe(NAV_BADGE_POLL_MS);
    expect(options?.refetchIntervalInBackground).toBe(false);
    expect(NAV_BADGE_POLL_MS).toBe(60_000);
  });

  it('says "tomorrow" for a tender due tomorrow and caps big counts', () => {
    const t = ((_k: string, o: { defaultValue: string }) => o.defaultValue) as never;
    expect(badgeText({ count: 1, kind: 'due', tone: 'warning', due_in_days: 1 }, t)).toBe('tomorrow');
    expect(badgeText({ count: 250, kind: 'open', tone: 'neutral' }, t)).toBe('99+');
  });

  it('stays silent when signed out', () => {
    useAuthStore.setState({ isAuthenticated: false, accessToken: null } as never);
    renderHook(() => useNavBadges(), { wrapper: wrap() });
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("gives a menu row its shortcut for the tooltip", () => {
    registerAppActions();
    const { result } = renderHook(() => useNavItemShortcut('/boq'), { wrapper: wrap() });
    expect(result.current).toBe('G B');
  });
});

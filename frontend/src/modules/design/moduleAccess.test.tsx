// Core patch 0009: a person gets Design from the server's saved choice, with what it links to, and a
// switched-off /design/* page offers the switch instead of a 404.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes } from 'react-router-dom';

const http = vi.hoisted(() => ({ server: {} as Record<string, boolean>, patched: [] as Record<string, boolean>[] }));
vi.mock('@/shared/lib/api', async (orig) => ({
  ...(await orig<object>()),
  apiGet: vi.fn(async () => ({ modules: http.server })),
  apiPatch: vi.fn(async (_p: string, body: { modules: Record<string, boolean> }) => { http.patched.push(body.modules); return body; }),
}));

import { useModuleStore } from '@/stores/useModuleStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useModuleRouteElements } from '@/modules/ModuleRoutes';

const Wrapper = ({ children }: { title: string; children: React.ReactNode }) => <>{children}</>;
function AppRoutes() {
  return <Routes>{useModuleRouteElements({ Wrapper })}</Routes>;
}

beforeEach(() => {
  cleanup();
  vi.useRealTimers();
  http.server = {};
  http.patched = [];
  useModuleStore.setState({ enabledModules: { design: false, schedule: false, tendering: true }, syncedOnce: false });
});

describe('module switch keeps what Design links to', () => {
  it('switching Design on switches schedule and tendering on', () => {
    useModuleStore.getState().setModuleEnabled('design', true);
    const on = useModuleStore.getState().enabledModules;
    expect([on.design, on.schedule, on.tendering]).toEqual([true, true, true]);
  });

  it('switching Design off leaves the others as they are', () => {
    useModuleStore.getState().setModuleEnabled('design', true);
    useModuleStore.getState().setModuleEnabled('design', false);
    expect(useModuleStore.getState().enabledModules.schedule).toBe(true);
  });
});

describe('server choice wins over a stale browser copy', () => {
  it('design on at the server shows even when this browser stored it off', async () => {
    http.server = { design: true, schedule: true, tendering: true };
    await useModuleStore.getState().syncFromServer();
    expect(useModuleStore.getState().isModuleEnabled('design')).toBe(true);
    expect(useModuleStore.getState().syncedOnce).toBe(true);
  });

  it('a profile that left schedule off is repaired and saved back', async () => {
    vi.useFakeTimers();
    http.server = { design: true, schedule: false, tendering: true };
    await useModuleStore.getState().syncFromServer();
    expect(useModuleStore.getState().enabledModules.schedule).toBe(true);
    await vi.advanceTimersByTimeAsync(1100);
    expect(http.patched.at(-1)?.schedule).toBe(true);
  });

  it('nothing to repair: nothing is written back', async () => {
    vi.useFakeTimers();
    http.server = { design: false };
    await useModuleStore.getState().syncFromServer();
    await vi.advanceTimersByTimeAsync(1100);
    expect(http.patched).toEqual([]);
  });
});

describe('a /design page while Design is off', () => {
  it('reads the server first, then offers the switch instead of a 404', async () => {
    useAuthStore.setState({ isAuthenticated: true });
    http.server = { design: false };
    render(<MemoryRouter initialEntries={['/design/overview']}><AppRoutes /></MemoryRouter>);
    const off = await screen.findByTestId('module-off');
    expect(off.textContent).toMatch(/disabled/);
    await userEvent.setup().click(screen.getByRole('button', { name: 'Enable' }));
    await act(async () => {});
    expect(useModuleStore.getState().enabledModules.design).toBe(true);
    expect(screen.queryByTestId('module-off')).toBeNull();
  });

  it('opens straight away when the server has it on', async () => {
    useAuthStore.setState({ isAuthenticated: true });
    http.server = { design: true };
    render(<MemoryRouter initialEntries={['/design/overview']}><AppRoutes /></MemoryRouter>);
    await act(async () => {});
    expect(screen.queryByTestId('module-off')).toBeNull();
    expect(useModuleStore.getState().isModuleEnabled('design')).toBe(true);
  });
});

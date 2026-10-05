// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: unknown) => {
      const o = (typeof opts === 'string' ? { defaultValue: opts } : (opts ?? {})) as Record<string, unknown>;
      const template = typeof o.defaultValue === 'string' ? o.defaultValue : key;
      return template.replace(/\{\{(\w+)\}\}/g, (_, n: string) => String(o[n] ?? ''));
    },
    i18n: { language: 'en', changeLanguage: vi.fn(), dir: () => 'ltr' },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPut: vi.fn() }));
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

import { useAuthStore } from '@/stores/useAuthStore';
import { meFixture } from './__fixtures__/me';
import { readbackFixture } from './__fixtures__/readback';
import { taskFixture } from './__fixtures__/task';
import { TRAINER_DOCK_ATTR, TRAINER_DOCK_OFFSET_VAR, TRAINER_SHEET_PEEK_VAR } from './dockGeometry';
import { TaskDock, isTrainerDockHiddenOn } from './TaskDock';
import { __resetTrainerCacheOwnerForTests } from './useTrainerMode';
import { DOCK_WIDTH_DEFAULT, useTrainerUiStore } from './useTrainerUiStore';

const TARGET = '/boq/7a4c1f0e-2b3d-4e5f-8a9b-0c1d2e3f4a5b';
const root = () => document.documentElement;
let client: QueryClient;
let academy = true;

function setViewport(width: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: width });
}

function renderDock(path = TARGET) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <TaskDock />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  academy = true;
  api.apiGet.mockReset();
  api.apiGet.mockImplementation(async (path: string) => {
    if (path === '/system/status') return { academy_mode: academy };
    if (path === '/v1/trainer/me') return meFixture;
    if (path === '/v1/trainer/tasks/t2-markups') return taskFixture;
    if (path === '/v1/trainer/tasks/t2-markups/readback') return readbackFixture;
    throw new Error(`unexpected GET ${path}`);
  });
  __resetTrainerCacheOwnerForTests();
  useAuthStore.setState({ isAuthenticated: true, userId: 'user-a', accessToken: null });
  useTrainerUiStore.getState().reset();
  useTrainerUiStore.getState().resetDockWidth();
  setViewport(1440);
  root().style.setProperty('--oe-sidebar-width', '248px');
  root().style.removeProperty('--oe-ai-dock-widget-offset');
  root().dir = 'ltr';
});
afterEach(() => {
  cleanup();
  client.clear();
  useAuthStore.setState({ isAuthenticated: false, userId: null, accessToken: null });
  root().style.removeProperty('--oe-sidebar-width');
  root().style.removeProperty('--oe-ai-dock-widget-offset');
  root().dir = '';
  document.body.style.overflow = '';
});

describe('when the dock shows', () => {
  it('stays away from the course map and from pages outside the shell', () => {
    expect(isTrainerDockHiddenOn('/academy')).toBe(true);
    expect(isTrainerDockHiddenOn('/academy/x')).toBe(true);
    expect(isTrainerDockHiddenOn('/chat')).toBe(true);
    expect(isTrainerDockHiddenOn('/login')).toBe(true);
    expect(isTrainerDockHiddenOn('/boq/1')).toBe(false);
    expect(isTrainerDockHiddenOn('/academyx')).toBe(false);
  });

  it('renders nothing without a task, and writes nothing on <html>', async () => {
    renderDock();
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(screen.queryByTestId('trainer-dock')).toBeNull();
    expect(root().hasAttribute(TRAINER_DOCK_ATTR)).toBe(false);
  });

  it('renders nothing when the box is not an academy box', async () => {
    academy = false;
    useTrainerUiStore.getState().openTask('t2-markups');
    renderDock();
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(screen.queryByTestId('trainer-dock')).toBeNull();
    expect(api.apiGet.mock.calls.some(([p]) => String(p).startsWith('/v1/trainer/'))).toBe(false);
  });

  it('renders nothing on the course map', async () => {
    useTrainerUiStore.getState().openTask('t2-markups');
    renderDock('/academy');
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(screen.queryByTestId('trainer-dock')).toBeNull();
  });
});

describe('push and rail', () => {
  it('pushes the page by its width on a wide screen and takes it back on unmount', async () => {
    useTrainerUiStore.getState().openTask('t2-markups');
    const view = renderDock();
    const dock = await screen.findByTestId('trainer-dock');
    expect(dock.getAttribute('data-mode')).toBe('push');
    expect(dock.tagName).toBe('ASIDE');
    expect(dock.getAttribute('aria-label')).toBe('Academy task');
    expect(dock.style.width).toBe(`${DOCK_WIDTH_DEFAULT}px`);
    expect(root().getAttribute(TRAINER_DOCK_ATTR)).toBe('push');
    expect(root().style.getPropertyValue(TRAINER_DOCK_OFFSET_VAR)).toBe(`${DOCK_WIDTH_DEFAULT}px`);
    expect(await screen.findByText(taskFixture.brief)).toBeTruthy();
    // The task chip belongs to the app header, not to the panel.
    expect(dock.textContent).not.toContain('Academy · Task 2 of 5');
    view.unmount();
    expect(root().hasAttribute(TRAINER_DOCK_ATTR)).toBe(false);
    expect(root().style.getPropertyValue(TRAINER_DOCK_OFFSET_VAR)).toBe('');
  });

  it('moves focus to the task heading when a task opens', async () => {
    useTrainerUiStore.getState().openTask('t2-markups');
    renderDock();
    const dock = await screen.findByTestId('trainer-dock');
    await waitFor(() => expect(dock.contains(document.activeElement)).toBe(true));
  });

  it('collapses to a 56px rail that still pushes, and expands again', async () => {
    useTrainerUiStore.getState().openTask('t2-markups');
    renderDock();
    await screen.findByTestId('trainer-dock');
    fireEvent.click(screen.getByTestId('trainer-dock-collapse'));
    const rail = await screen.findByTestId('trainer-rail-expand');
    expect(screen.getByTestId('trainer-dock').getAttribute('data-mode')).toBe('rail');
    expect(rail.getAttribute('aria-label')).toBe('Show task 2');
    expect(rail.textContent).toContain('Academy · Task 2 of 5');
    expect(root().getAttribute(TRAINER_DOCK_ATTR)).toBe('push');
    expect(root().style.getPropertyValue(TRAINER_DOCK_OFFSET_VAR)).toBe('56px');
    fireEvent.click(rail);
    expect(screen.getByTestId('trainer-dock').getAttribute('data-mode')).toBe('push');
  });

  it('folds to the rail when the AI dock opens and leaves no room', async () => {
    useTrainerUiStore.getState().openTask('t2-markups');
    renderDock();
    expect((await screen.findByTestId('trainer-dock')).getAttribute('data-mode')).toBe('push');
    act(() => {
      root().style.setProperty('--oe-ai-dock-widget-offset', '440px');
    });
    await waitFor(() => expect(screen.getByTestId('trainer-dock').getAttribute('data-mode')).toBe('rail'));
    // The learner can still open it: it then pushes at the narrowest width.
    fireEvent.click(screen.getByTestId('trainer-rail-expand'));
    const dock = screen.getByTestId('trainer-dock');
    expect(dock.getAttribute('data-mode')).toBe('push');
    expect(dock.style.width).toBe('320px');
  });

  it('resizes from the keyboard, towards the page widens, mirrored in RTL', async () => {
    useTrainerUiStore.getState().openTask('t2-markups');
    renderDock();
    const handle = await screen.findByTestId('trainer-dock-resize');
    expect(handle.getAttribute('role')).toBe('separator');
    expect(handle.getAttribute('aria-valuenow')).toBe('380');
    fireEvent.keyDown(handle, { key: 'ArrowLeft' });
    expect(useTrainerUiStore.getState().dockWidth).toBe(396);
    expect(root().style.getPropertyValue(TRAINER_DOCK_OFFSET_VAR)).toBe('396px');
    root().dir = 'rtl';
    fireEvent.keyDown(handle, { key: 'ArrowLeft' });
    expect(useTrainerUiStore.getState().dockWidth).toBe(380);
    fireEvent.doubleClick(handle);
    expect(useTrainerUiStore.getState().dockWidth).toBe(DOCK_WIDTH_DEFAULT);
  });
});

describe('the phone sheet', () => {
  it('peeks at 64px, expands into a dialog, and Esc folds it back', async () => {
    setViewport(400);
    useTrainerUiStore.getState().openTask('t2-markups');
    renderDock();
    const sheet = await screen.findByTestId('trainer-dock');
    expect(sheet.getAttribute('data-mode')).toBe('sheet');
    expect(sheet.style.height).toBe('64px');
    expect(root().getAttribute(TRAINER_DOCK_ATTR)).toBe('sheet');
    expect(root().style.getPropertyValue(TRAINER_SHEET_PEEK_VAR)).toBe('64px');
    const toggle = screen.getByTestId('trainer-sheet-toggle');
    expect(toggle.textContent).toContain('Task 2 · Add overheads and profit');
    fireEvent.click(toggle);
    const dialog = screen.getByRole('dialog');
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(dialog.style.height).toBe('85vh');
    expect(document.body.style.overflow).toBe('hidden');
    expect(await screen.findByText(taskFixture.brief)).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByTestId('trainer-dock').style.height).toBe('64px');
    expect(document.body.style.overflow).toBe('');
  });
});

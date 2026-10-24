// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The palette as an action palette: actions run, "project > page" targets a
 * project, unknown text hands over to the AI dock prefilled (never sent), a
 * shortcut can be rebound and a clash is refused, and an AI suggestion runs
 * only on the person's click.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, act } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

const projectsList = vi.fn();
vi.mock('@/features/projects/api', () => ({ projectsApi: { list: () => projectsList() } }));
vi.mock('@/features/boq/api', () => ({ boqApi: { list: () => Promise.resolve([]) } }));
vi.mock('@/shared/lib/api', () => ({ apiGet: () => Promise.resolve({ hits: [] }) }));

import { CommandPalette } from './CommandPalette';
import { UiActionCard } from '@/features/erp-chat/actions/UiActionCard';
import { useFloatingChatStore } from '@/features/erp-chat/useFloatingChat';
import { useShortcutStore } from '@/shared/lib/actions/shortcuts';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useThemeStore } from '@/stores/useThemeStore';

function Where() {
  const loc = useLocation();
  return <div data-testid="where">{loc.pathname + loc.search}</div>;
}

function renderPalette(onClose = vi.fn(), at = '/') {
  render(
    <MemoryRouter initialEntries={[at]}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              <CommandPalette open onClose={onClose} />
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
  return onClose;
}

function typeQuery(text: string) {
  fireEvent.change(screen.getByRole('textbox'), { target: { value: text } });
}

beforeEach(() => {
  localStorage.clear();
  projectsList.mockResolvedValue([
    { id: 'p-berlin', name: 'Berlin Office Tower', description: '' },
    { id: 'p-munich', name: 'Munich Depot', description: '' },
  ]);
  useFloatingChatStore.setState({ isOpen: false, pendingPrompt: null });
  useShortcutStore.setState({ overrides: {} });
  useProjectContextStore.setState({ activeProjectId: null, activeProjectName: '' });
});

describe('CommandPalette actions', () => {
  it('finds an action by fuzzy text and runs it', async () => {
    const onClose = renderPalette();
    typeQuery('dark them');
    const row = await screen.findByTestId('palette-row-theme.dark');
    fireEvent.click(row.querySelector('button')!);
    expect(useThemeStore.getState().theme).toBe('dark');
    expect(onClose).toHaveBeenCalled();
  });

  it('shows the shortcut of an action', async () => {
    renderPalette();
    typeQuery('new estimate');
    const row = await screen.findByTestId('palette-row-boq.new');
    expect(row.textContent).toContain('N E');
  });

  it('runs "project Berlin > quantities" against that project', async () => {
    renderPalette();
    await waitFor(() => expect(projectsList).toHaveBeenCalled());
    await act(async () => {});
    typeQuery('project Berlin > quantities');
    const row = await screen.findByTestId('palette-row-project.quantities@p-berlin');
    expect(row.textContent).toContain('Berlin Office Tower');
    fireEvent.click(row.querySelector('button')!);
    expect(useProjectContextStore.getState().activeProjectId).toBe('p-berlin');
    expect(screen.getByTestId('where').textContent).toBe('/quantities');
  });

  it('hands unknown text to the AI dock, prefilled and not sent', async () => {
    const onClose = renderPalette();
    typeQuery('how much concrete is in level 2?');
    const ask = await screen.findByTestId('palette-row-ask-ai');
    // A question matches no action, so "Ask AI" is the first row and Enter takes it.
    expect(screen.getAllByTestId(/^palette-row-/)[0]).toBe(ask);
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    expect(onClose).toHaveBeenCalled();
    const chat = useFloatingChatStore.getState();
    expect(chat.isOpen).toBe(true);
    expect(chat.pendingPrompt).toBe('how much concrete is in level 2?');
  });

  it('leaves the full-page chat for the dock when asked from there', async () => {
    renderPalette(vi.fn(), '/chat');
    typeQuery('what is open');
    fireEvent.click((await screen.findByTestId('palette-row-ask-ai')).querySelector('button')!);
    expect(screen.getByTestId('where').textContent).toBe('/');
    expect(useFloatingChatStore.getState().pendingPrompt).toBe('what is open');
  });

  it('rebinds a shortcut and refuses one that is taken or reserved', async () => {
    renderPalette();
    typeQuery('dark theme');
    fireEvent.click(await screen.findByTestId('palette-rebind-theme.dark'));
    const dialog = screen.getByRole('dialog');
    // Taken: G then B opens the BOQ.
    fireEvent.keyDown(dialog, { key: 'g', code: 'KeyG' });
    fireEvent.keyDown(dialog, { key: 'b', code: 'KeyB' });
    expect(screen.getByTestId('palette-recording').textContent).toMatch(/Already used/);
    // Reserved by the browser.
    fireEvent.keyDown(dialog, { key: 't', code: 'KeyT', ctrlKey: true });
    expect(screen.getByTestId('palette-recording').textContent).toMatch(/browser or the system/);
    // Free.
    fireEvent.keyDown(dialog, { key: 'd', code: 'KeyD', ctrlKey: true, altKey: true });
    expect(useShortcutStore.getState().overrides['theme.dark']).toBe('Mod+Alt+D');
    expect(screen.queryByTestId('palette-recording')).toBeNull();
  });
});

describe('AI action suggestion card', () => {
  it('shows the confidence and runs only on click', () => {
    render(
      <MemoryRouter>
        <UiActionCard data={{ action_id: 'project.new', confidence: 0.86, reason: 'You asked for a new job.' }} />
        <Where />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('ui-action-card').textContent).toContain('86');
    expect(screen.getByTestId('where').textContent).toBe('/');
    fireEvent.click(screen.getByText('Run'));
    expect(screen.getByTestId('where').textContent).toBe('/projects/new');
  });

  it('does not guess at an id this browser does not know', () => {
    render(
      <MemoryRouter>
        <UiActionCard data={{ action_id: 'nope.unknown', confidence: 0.9 }} />
      </MemoryRouter>,
    );
    expect(screen.queryByText('Run')).toBeNull();
  });
});

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const apiGet = vi.fn();
const fetchProjectList = vi.fn();
vi.mock('@/shared/lib/api', () => ({ apiGet: (...a: unknown[]) => apiGet(...a) }));
vi.mock('@/shared/lib/projectList', () => ({ fetchProjectList: () => fetchProjectList() }));

import { DemoSwitcherBar, captureDemoPick } from './DemoSwitcherBar';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAppearanceStore } from '@/stores/useAppearanceStore';
import { useModuleStore } from '@/stores/useModuleStore';
import { useMenuLayoutStore } from '@/app/layout/useMenuLayoutStore';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';

function renderBar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <DemoSwitcherBar />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const PROJECTS = [
  { id: 'p1', name: 'Consultancy', metadata: { demo_id: 'office-london' } },
  { id: 'p2', name: 'Contractor', metadata: { demo_id: 'medical-us' } },
  { id: 'p3', name: 'School', metadata: { demo_id: 'school-paris' } },
  { id: 'p9', name: 'Mine', metadata: {} },
];

describe('DemoSwitcherBar', () => {
  beforeEach(() => {
    apiGet.mockReset();
    fetchProjectList.mockReset();
    sessionStorage.clear();
  });

  it('renders nothing outside demo mode', async () => {
    apiGet.mockResolvedValue({ demo_mode: false });
    const { container } = renderBar();
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    expect(container.querySelector('nav')).toBeNull();
    expect(fetchProjectList).not.toHaveBeenCalled();
  });

  it('shows only the demos this account can open', async () => {
    apiGet.mockResolvedValue({ demo_mode: true });
    fetchProjectList.mockResolvedValue(PROJECTS);
    renderBar();
    const tabs = await screen.findAllByRole('tab');
    expect(tabs).toHaveLength(3);
    tabs.forEach((tab) => expect(tab).not.toBeDisabled());
    expect(tabs.map((tab) => tab.getAttribute('title'))).toEqual(['Consultancy', 'Contractor', 'School']);
  });

  it('marks each demo with its photo in a hexagon, and a drawing when the photo fails', async () => {
    // A chosen demo keeps the bar from sending a first visit to the chooser.
    sessionStorage.setItem('oe_demo_chosen', 'office-london');
    apiGet.mockResolvedValue({ demo_mode: true });
    fetchProjectList.mockResolvedValue(PROJECTS);
    renderBar();
    const tabs = await screen.findAllByRole('tab');
    for (const tab of tabs) {
      const hex = tab.querySelector('[data-testid="hex-mark"]')!;
      expect(hex).not.toBeNull();
      expect(hex.getAttribute('data-hex-photo')).toBe('true');
      expect(hex.querySelector('img')!.getAttribute('src')).toMatch(/cmt-.+\.webp$/);
    }
    fireEvent.error(tabs[0]!.querySelector('[data-testid="hex-mark"] img')!);
    await waitFor(() => {
      const first = screen.getAllByRole('tab')[0]!.querySelector('[data-testid="hex-mark"]')!;
      expect(first.getAttribute('data-hex-photo')).toBe('false');
      expect(first.querySelector('svg')).not.toBeNull();
    });
  });

  it('renders nothing when no demo project is visible', async () => {
    apiGet.mockResolvedValue({ demo_mode: true });
    fetchProjectList.mockResolvedValue([PROJECTS[2]]);
    const { container } = renderBar();
    await waitFor(() => expect(fetchProjectList).toHaveBeenCalled());
    expect(container.querySelector('nav')).toBeNull();
  });

  it('applies a ?demo= deep link once projects load', async () => {
    captureDemoPick('?demo=medical-us');
    captureDemoPick('?demo=unknown');
    apiGet.mockResolvedValue({ demo_mode: true });
    fetchProjectList.mockResolvedValue(PROJECTS);
    renderBar();
    await waitFor(() => expect(useProjectContextStore.getState().activeProjectId).toBe('p2'));
    expect(sessionStorage.getItem('oe_demo_pick')).toBeNull();
  });

  it('gives the US demo its own look and leaves the menu to the demo filter', async () => {
    useAppearanceStore.getState().setAppearance({ accent: 'blue', font: 'system', density: 'comfortable', radius: 'standard', text: 'default', look: 'standard' });
    useModuleStore.getState().setHiddenGroups(['grp_real_estate']);
    captureDemoPick('?demo=medical-us');
    apiGet.mockResolvedValue({ demo_mode: true });
    fetchProjectList.mockResolvedValue(PROJECTS);
    renderBar();
    await waitFor(() => expect(sessionStorage.getItem('oe_demo_chosen')).toBe('medical-us'));
    expect(useAppearanceStore.getState().effective.accent).toBe('amber');
    // Sections hidden by an earlier switcher build are let go; `useDemoModules`
    // cuts the menu now.
    expect(useModuleStore.getState().hiddenGroups).toEqual([]);
    expect(document.documentElement.dataset.oeMenu).toBe('dark');
  });

  it('takes the menu style off again when the bar goes away', async () => {
    captureDemoPick('?demo=medical-us');
    apiGet.mockResolvedValue({ demo_mode: true });
    fetchProjectList.mockResolvedValue(PROJECTS);
    const { unmount } = renderBar();
    await waitFor(() => expect(document.documentElement.dataset.oeMenu).toBe('dark'));
    unmount();
    expect(document.documentElement.dataset.oeMenu).toBeUndefined();
  });

  it('sends a visitor who has not chosen yet to the picker', async () => {
    apiGet.mockResolvedValue({ demo_mode: true });
    fetchProjectList.mockResolvedValue(PROJECTS);
    renderBar();
    await waitFor(() => expect(screen.queryByRole('tablist')).toBeNull());
  });

  it('opens a demo in its work mode, so the menu is the short list of that company', async () => {
    useMenuLayoutStore.getState().dispatch({ type: 'setMode', mode: 'all' });
    captureDemoPick('?demo=medical-us');
    apiGet.mockResolvedValue({ demo_mode: true });
    fetchProjectList.mockResolvedValue(PROJECTS);
    renderBar();
    await waitFor(() => expect(useMenuLayoutStore.getState().layout.activeMode).toBe('manager'));
  });

  it('applies the demo work mode on reload once per session, then leaves a later choice alone', async () => {
    useMenuLayoutStore.getState().dispatch({ type: 'setMode', mode: 'all' });
    sessionStorage.setItem('oe_demo_chosen', 'office-london');
    apiGet.mockResolvedValue({ demo_mode: true });
    fetchProjectList.mockResolvedValue(PROJECTS);
    const first = renderBar();
    await waitFor(() => expect(useMenuLayoutStore.getState().layout.activeMode).toBe('finance'));
    first.unmount();
    useMenuLayoutStore.getState().dispatch({ type: 'setMode', mode: 'all' });
    renderBar();
    await screen.findAllByRole('tab');
    expect(useMenuLayoutStore.getState().layout.activeMode).toBe('all');
  });

  it('names the current language, never a placeholder, when the demo is in another language', async () => {
    captureDemoPick('?demo=school-paris');
    apiGet.mockResolvedValue({ demo_mode: true });
    fetchProjectList.mockResolvedValue(PROJECTS);
    renderBar();
    await waitFor(() => expect(useProjectContextStore.getState().activeProjectId).toBe('p3'));
    const select = (await screen.findByTestId('demo-market-switch')) as HTMLSelectElement;
    expect(select.value).toBe('');
    const shown = select.options[select.selectedIndex]!.textContent;
    // The test i18n stores no language, as on a first visit: English is what is on screen.
    expect(SUPPORTED_LANGUAGES.map((l) => l.name)).toContain(shown);
    expect(shown).toMatch(/^English/);
    expect(shown).not.toMatch(/select/i);
  });

  it('folds the strip on a phone to one line that opens the tabs', async () => {
    captureDemoPick('?demo=medical-us');
    apiGet.mockResolvedValue({ demo_mode: true });
    fetchProjectList.mockResolvedValue(PROJECTS);
    renderBar();
    const toggle = await screen.findByTestId('demo-switcher-toggle');
    const body = screen.getByTestId('demo-switcher-body');
    expect(body.className).toMatch(/(^|\s)hidden(\s|$)/);
    expect(body.className).toContain('sm:flex');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(body.className).not.toMatch(/(^|\s)hidden(\s|$)/);
  });
});

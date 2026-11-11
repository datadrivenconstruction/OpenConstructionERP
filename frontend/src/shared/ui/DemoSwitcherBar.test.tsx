// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
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
    expect(tabs).toHaveLength(2);
    tabs.forEach((tab) => expect(tab).not.toBeDisabled());
    expect(tabs.map((tab) => tab.getAttribute('title'))).toEqual(['Consultancy', 'Contractor']);
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

  it('gives the US demo its own look and a shorter menu', async () => {
    useAppearanceStore.getState().setAppearance({ accent: 'blue', font: 'system', density: 'comfortable', radius: 'standard', text: 'default', look: 'standard' });
    useModuleStore.getState().setHiddenGroups([]);
    captureDemoPick('?demo=medical-us');
    apiGet.mockResolvedValue({ demo_mode: true });
    fetchProjectList.mockResolvedValue(PROJECTS);
    renderBar();
    await waitFor(() => expect(sessionStorage.getItem('oe_demo_chosen')).toBe('medical-us'));
    expect(useAppearanceStore.getState().effective.accent).toBe('amber');
    const hidden = useModuleStore.getState().hiddenGroups;
    expect(hidden).toContain('grp_real_estate');
    expect(hidden).not.toContain('grp_estimating');
    expect(hidden).not.toContain('grp_learn');
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
});

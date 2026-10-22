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
  { id: 'p1', name: 'Consultancy', metadata: { demo_id: 'consultancy-riyadh' } },
  { id: 'p2', name: 'Contractor', metadata: { demo_id: 'contractor-jeddah' } },
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

  it('shows four tabs and disables demos that are not installed', async () => {
    apiGet.mockResolvedValue({ demo_mode: true });
    fetchProjectList.mockResolvedValue(PROJECTS);
    renderBar();
    const tabs = await screen.findAllByRole('tab');
    expect(tabs).toHaveLength(4);
    await waitFor(() => expect(tabs[0]).not.toBeDisabled());
    expect(tabs[1]).not.toBeDisabled();
    expect(tabs[2]).toBeDisabled();
    expect(tabs[3]).toBeDisabled();
  });

  it('applies a ?demo= deep link once projects load', async () => {
    captureDemoPick('?demo=contractor-jeddah');
    captureDemoPick('?demo=unknown');
    apiGet.mockResolvedValue({ demo_mode: true });
    fetchProjectList.mockResolvedValue(PROJECTS);
    renderBar();
    await waitFor(() => expect(useProjectContextStore.getState().activeProjectId).toBe('p2'));
    expect(sessionStorage.getItem('oe_demo_pick')).toBeNull();
  });
});

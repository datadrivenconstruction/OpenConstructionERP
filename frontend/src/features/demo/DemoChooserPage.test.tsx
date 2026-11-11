// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const apiGet = vi.fn();
const fetchProjectList = vi.fn();
vi.mock('@/shared/lib/api', () => ({ apiGet: (...a: unknown[]) => apiGet(...a) }));
vi.mock('@/shared/lib/projectList', () => ({ fetchProjectList: () => fetchProjectList() }));

import { DemoChooserPage } from './DemoChooserPage';
import { applyDemoMenuStyle } from '@/shared/lib/demoProfiles';

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <DemoChooserPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const PROJECTS = [
  { id: 'p1', name: 'London', metadata: { demo_id: 'office-london' } },
  { id: 'p2', name: 'Berlin', metadata: { demo_id: 'residential-berlin' } },
  { id: 'p3', name: 'Showcase', metadata: { demo_id: 'full-showcase-riyadh' } },
];

describe('DemoChooserPage', () => {
  beforeEach(() => {
    apiGet.mockReset();
    fetchProjectList.mockReset();
    sessionStorage.clear();
    applyDemoMenuStyle(null);
    apiGet.mockResolvedValue({ demo_mode: true });
    fetchProjectList.mockResolvedValue(PROJECTS);
  });

  it('puts the full platform first and highlights it', async () => {
    renderPage();
    const cards = await screen.findAllByTestId(/^demo-card-/);
    expect(cards.map((c) => c.getAttribute('data-testid'))).toEqual([
      'demo-card-full-showcase-riyadh',
      'demo-card-office-london',
      'demo-card-residential-berlin',
    ]);
    expect(cards[0].getAttribute('data-featured')).toBe('true');
    expect(cards[1].getAttribute('data-featured')).toBeNull();
    expect(screen.getByText('Full platform: every module')).toBeTruthy();
    expect(screen.getByText('Or start from a variant cut to one kind of company')).toBeTruthy();
  });

  it('shows the Berlin card only when that demo is installed', async () => {
    fetchProjectList.mockResolvedValue([PROJECTS[0]]);
    renderPage();
    await screen.findByTestId('demo-card-office-london');
    expect(screen.queryByTestId('demo-card-residential-berlin')).toBeNull();
  });

  it('applies the card menu style when a demo opens', async () => {
    renderPage();
    await userEvent.click(await screen.findByTestId('demo-card-residential-berlin'));
    await waitFor(() => expect(document.documentElement.dataset.oeMenu).toBe('outline'));
    await userEvent.click(screen.getByTestId('demo-card-full-showcase-riyadh'));
    await waitFor(() => expect(document.documentElement.dataset.oeMenu).toBeUndefined());
  });

  it('links the footer to the packs and settings pages', async () => {
    renderPage();
    await screen.findByTestId('demo-card-full-showcase-riyadh');
    expect(screen.getByTestId('demo-footer-packs').getAttribute('href')).toBe('/packs');
    expect(screen.getByTestId('demo-footer-settings').getAttribute('href')).toBe('/settings');
  });
});

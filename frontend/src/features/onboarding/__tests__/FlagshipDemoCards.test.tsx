// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Run:  npx vitest run src/features/onboarding/__tests__/FlagshipDemoCards.test.tsx
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const { apiGet, apiPost, navigate } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock('@/shared/lib/api', () => ({ apiGet, apiPost }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (_k: string, o?: { defaultValue?: string }) => o?.defaultValue ?? _k }),
}));
vi.mock('react-router-dom', async (orig) => ({ ...(await orig()), useNavigate: () => navigate }));
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: unknown) => unknown) => sel({ addToast: vi.fn() }),
}));

import { FlagshipDemoCards } from '../FlagshipDemoCards';
import { demosForMarket } from '../flagshipDemos';

const CATALOG = [
  { demo_id: 'residential-berlin', name: 'Berlin flats', description: 'Housing', country: 'DE' },
  { demo_id: 'office-frankfurt', name: 'Frankfurt office', description: 'Office', country: 'DE' },
  { demo_id: 'contractor-jeddah', name: 'Jeddah tower', description: 'Tower', country: 'SA' },
];

function renderCards(country: string | null) {
  apiGet.mockResolvedValue(CATALOG);
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><FlagshipDemoCards country={country} /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('demosForMarket', () => {
  it('gives Saudi Arabia the four curated cards', () => {
    expect(demosForMarket('sa', CATALOG).demos.map((d) => d.id)).toEqual([
      'consultancy-riyadh', 'contractor-jeddah', 'site-development-dammam', 'full-showcase-riyadh',
    ]);
  });

  it('gives another market only its own demos', () => {
    const r = demosForMarket('de', CATALOG);
    expect(r.matched).toBe(true);
    expect(r.demos.map((d) => d.id)).toEqual(['residential-berlin', 'office-frankfurt']);
  });

  it('offers no foreign project when the market has none', () => {
    const r = demosForMarket('is', CATALOG);
    expect(r.matched).toBe(false);
    expect(r.demos).toEqual([]);
  });
});

describe('FlagshipDemoCards', () => {
  it('says plainly that a market has no demo yet', async () => {
    renderCards('is');
    await screen.findByText(/No demo project for this market yet/);
    expect(screen.queryAllByRole('button')).toHaveLength(0);
  });

  it('shows a German reader German demos and no Saudi ones', async () => {
    renderCards('de');
    await screen.findByText('Berlin flats');
    expect(screen.queryByText('Marina Heights Residential Tower, Jeddah')).toBeNull();
    expect(screen.getAllByRole('button')).toHaveLength(2);
  });

  it('installs by id, shows a busy label, and opens the project', async () => {
    let resolve;
    apiPost.mockReturnValue(new Promise((r) => (resolve = r)));
    renderCards('sa');
    const button = screen.getByTestId('flagship-install-site-development-dammam');
    fireEvent.click(button);
    await waitFor(() => expect(button.getAttribute('aria-busy')).toBe('true'));
    expect(button.textContent).toContain('Installing…');
    resolve({ project_id: 'p-1' });
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/projects/p-1'));
    expect(apiPost.mock.calls[0][0]).toBe('/demo/install/site-development-dammam');
  });
});

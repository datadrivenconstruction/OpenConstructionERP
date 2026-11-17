// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { SiteBriefingCard } from '../SiteBriefingCard';
import type { BriefingEnvelope } from '../api';

vi.mock('@/shared/lib/permissionGates', () => ({ useHasPermission: () => true }));

const envelope = (over: Partial<BriefingEnvelope>): BriefingEnvelope => ({
  provider_used: null,
  degraded: true,
  confidence: 1,
  items: [],
  exists: true,
  is_today: true,
  day: '2026-11-16',
  ...over,
});

function mount(data: BriefingEnvelope) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SiteBriefingCard projectId="p1" loader={() => Promise.resolve(data)} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('SiteBriefingCard', () => {
  it('renders facts and the degraded banner without a narrative', async () => {
    mount(
      envelope({
        items: [
          {
            id: 'rfis_overdue',
            section: 'rfis',
            count: 1,
            confidence: 1,
            entries: [{ ref: 'RFI-7', title: 'Slab edge', due: '2026-11-10' }],
          },
        ],
      }),
    );
    await waitFor(() => expect(screen.getByTestId('site-briefing-rfis_overdue')).toBeTruthy());
    expect(screen.getByText('Overdue RFIs (1)')).toBeTruthy();
    expect(screen.getByText('RFI-7')).toBeTruthy();
    expect(screen.getByTestId('site-ai-degraded-banner')).toBeTruthy();
    expect(screen.queryByTestId('site-briefing-narrative')).toBeNull();
  });

  it('shows the narrative and no banner when a provider answered', async () => {
    mount(envelope({ degraded: false, provider_used: 'x', narrative: 'Two RFIs need you.', items: [] }));
    await waitFor(() => expect(screen.getByTestId('site-briefing-narrative').textContent).toBe('Two RFIs need you.'));
    expect(screen.queryByTestId('site-ai-degraded-banner')).toBeNull();
  });

  it('renders nothing in field mode when there is no briefing', async () => {
    const { container } = mount(envelope({ exists: false }));
    await waitFor(() => expect(container.querySelector('[data-testid="site-briefing-card"]')).toBeNull());
  });
});

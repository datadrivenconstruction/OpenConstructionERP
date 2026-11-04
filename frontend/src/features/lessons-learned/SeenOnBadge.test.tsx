// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import type { SeenResult } from './api';

const api = vi.hoisted(() => ({ seen: vi.fn() }));
vi.mock('./api', () => ({ lessonsApi: api }));

const moduleState = vi.hoisted(() => ({ enabled: true }));
vi.mock('@/stores/useModuleStore', () => ({
  useModuleStore: (sel: (s: { isModuleEnabled: (k: string) => boolean }) => unknown) =>
    sel({ isModuleEnabled: () => moduleState.enabled }),
}));

import { SeenOnBadge } from './SeenOnBadge';

const result: SeenResult = {
  projects: 3,
  lessons: 4,
  top: [
    { id: 'l1', project_id: 'p2', title: 'Late rebar delivery', recommendation: 'Order 6 weeks ahead', impact: 'high', matched: ['trade'] },
  ],
};

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SeenOnBadge projectId="p1" trade="Concrete" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('SeenOnBadge', () => {
  beforeEach(() => {
    api.seen.mockReset();
    moduleState.enabled = true;
  });

  it('shows the project count and opens the lessons', async () => {
    api.seen.mockResolvedValue(result);
    mount();
    const badge = await screen.findByTestId('seen-on-badge');
    expect(badge.textContent).toContain('3');
    expect(api.seen).toHaveBeenCalledWith({ projectId: 'p1', trade: 'Concrete', costCode: undefined, riskCategory: undefined });
    fireEvent.click(badge);
    expect(screen.getByText('Late rebar delivery')).toBeTruthy();
    expect(screen.getByText('Order 6 weeks ahead')).toBeTruthy();
  });

  it('renders nothing when no past project matches', async () => {
    api.seen.mockResolvedValue({ projects: 0, lessons: 0, top: [] });
    mount();
    await waitFor(() => expect(api.seen).toHaveBeenCalled());
    expect(screen.queryByTestId('seen-on-badge')).toBeNull();
  });

  it('does not query while the module is off', () => {
    moduleState.enabled = false;
    mount();
    expect(api.seen).not.toHaveBeenCalled();
    expect(screen.queryByTestId('seen-on-badge')).toBeNull();
  });
});

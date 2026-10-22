// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Run:  npx vitest run src/features/onboarding/__tests__/FlagshipDemoCards.test.tsx
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const { apiPost, navigate } = vi.hoisted(() => ({ apiPost: vi.fn(), navigate: vi.fn() }));

vi.mock('@/shared/lib/api', () => ({ apiPost }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (_k: string, o?: { defaultValue?: string }) => o?.defaultValue ?? _k }),
}));
vi.mock('react-router-dom', async (orig) => ({ ...(await orig()), useNavigate: () => navigate }));
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: (sel: (s: unknown) => unknown) => sel({ addToast: vi.fn() }),
}));

import { FlagshipDemoCards } from '../FlagshipDemoCards';
import { FLAGSHIP_DEMOS } from '../flagshipDemos';

describe('FlagshipDemoCards', () => {
  it('shows the four flagship demos', () => {
    render(<MemoryRouter><FlagshipDemoCards /></MemoryRouter>);
    expect(FLAGSHIP_DEMOS.map((d) => d.id)).toEqual([
      'consultancy-riyadh', 'contractor-jeddah', 'site-development-dammam', 'full-showcase-riyadh',
    ]);
    expect(screen.getByText('Marina Heights Residential Tower, Jeddah')).toBeTruthy();
    expect(screen.getAllByRole('button')).toHaveLength(4);
  });

  it('installs by id and opens the project', async () => {
    apiPost.mockResolvedValue({ project_id: 'p-1' });
    render(<MemoryRouter><FlagshipDemoCards /></MemoryRouter>);
    fireEvent.click(screen.getByTestId('flagship-install-site-development-dammam'));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/projects/p-1'));
    expect(apiPost.mock.calls[0][0]).toBe('/demo/install/site-development-dammam');
  });
});

// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const apiMocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  getErrorMessage: (e: unknown) => (e instanceof Error ? e.message : String(e)),
  ApiError: class ApiError extends Error {},
  getAuthToken: () => null,
  API_BASE: '/api',
}));
vi.mock('@/shared/lib/api', () => apiMocks);

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      let s = String(opts?.defaultValue ?? key);
      for (const [k, v] of Object.entries(opts ?? {})) s = s.replace(`{{${k}}}`, String(v));
      return s;
    },
    i18n: { language: 'en' },
  }),
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

import { StatutoryChecksSection } from '../StatutoryChecksSection';
import { buildStatutoryFacts } from '../facts';

const TX = {
  code: 'US-TX',
  name: 'Texas',
  country: 'US',
  verify_note: '',
  sectors: ['private', 'public'],
  claimant_roles: ['direct_contractor', 'subcontractor', 'supplier'],
  events: ['completion'],
  monthly_notices: true,
  notice_rules: [],
};

function routeGets(subdivision: string | null, codes: string[]) {
  apiMocks.apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/projects/')) return Promise.resolve({ id: 'p1', currency: 'USD', subdivision_code: subdivision });
    if (path === '/v1/statutory/jurisdictions/') return Promise.resolve(codes);
    if (path.startsWith('/v1/statutory/jurisdictions/US-TX')) return Promise.resolve(TX);
    return Promise.reject(new Error(`unexpected ${path}`));
  });
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StatutoryChecksSection projectId="p1" />
    </QueryClientProvider>,
  );
}

describe('StatutoryChecksSection', () => {
  beforeEach(() => {
    apiMocks.apiGet.mockReset();
    apiMocks.apiPost.mockReset();
  });

  it('stays hidden when no loaded pack carries the project subdivision', async () => {
    routeGets('US-OH', ['US-TX']);
    const { container } = mount();
    await waitFor(() => expect(apiMocks.apiGet).toHaveBeenCalledWith('/v1/statutory/jurisdictions/'));
    expect(container.querySelector('[data-testid="statutory-checks"]')).toBeNull();
  });

  it('stays hidden for a project with no subdivision', async () => {
    routeGets(null, ['US-TX']);
    const { container } = mount();
    await waitFor(() => expect(apiMocks.apiGet).toHaveBeenCalledTimes(1));
    expect(container.querySelector('[data-testid="statutory-checks"]')).toBeNull();
  });

  it('shows the Texas retainage verdict from the worked example', async () => {
    routeGets('US-TX', ['US-TX']);
    apiMocks.apiPost.mockResolvedValue({
      jurisdiction: 'US-TX',
      name: 'Texas',
      notices: [],
      retention: {
        retention_pct: '10',
        cap_pct: '10',
        cap_source: 'Tex. Prop. Code § 53.101',
        cap_amount: '25000.00',
        over_cap: false,
        needs_agreement_date: false,
      },
      findings: [],
      verify_note: '',
    });
    mount();
    expect(await screen.findByText('Statutory checks')).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: 'Retainage' }));
    fireEvent.click(screen.getByRole('button', { name: 'Check' }));
    expect(await screen.findByText('Within the cap')).toBeTruthy();
    expect(screen.getByText('Tex. Prop. Code § 53.101')).toBeTruthy();
    expect(apiMocks.apiPost.mock.calls[0]?.[0]).toBe('/v1/statutory/evaluate/');
  });
});

describe('buildStatutoryFacts', () => {
  it('leaves blank inputs out rather than sending zero', () => {
    const facts = buildStatutoryFacts('US-TX', {
      role: 'subcontractor',
      sector: 'private',
      events: { completion: '2026-10-20', last_work: '' },
      contractValue: ' ',
      paymentAmount: '250000',
      retentionAmount: '',
    });
    expect(facts.contract_value).toBeNull();
    expect(facts.retention).toBeNull();
    expect(facts.notices).toEqual({ role: 'subcontractor', events: { completion: '2026-10-20' } });
  });
});

// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Issue #435, the navigation half, on the change-order detail view. A change
// order mirrored from a variation carries the variation's ids and, once it is
// linked, the contract's id on its metadata, and the "Related" strip drew a
// pill for each - then navigated to the bare variations register and the bare
// contract register, throwing away the very id that decided whether to draw
// the pill. What is asserted here is the destination each pill navigates to.
//
// The harness is the one theBillPickerReachesTheChainApprover.test.tsx uses,
// because the pills live in the same detail view and need the same chrome.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const navigateSpy = vi.fn();

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useNavigate: () => navigateSpy,
    useParams: () => ({}),
    useSearchParams: () => [new URLSearchParams('?highlight=co-1'), vi.fn()],
  };
});

vi.mock('react-i18next', () => {
  type Opts = Record<string, unknown>;
  const fill = (template: string, opts?: Opts): string => {
    if (!opts) return template;
    const scope = (opts.replace as Opts | undefined) ?? opts;
    return template.replace(/\{\{(\w+)\}\}/g, (_match, name: string) =>
      scope[name] === undefined ? `{{${name}}}` : String(scope[name]),
    );
  };
  return {
    useTranslation: () => ({
      t: (key: string, second?: string | Opts, third?: Opts) => {
        if (typeof second === 'string') return fill(second, third);
        const dflt = second?.defaultValue;
        return fill(typeof dflt === 'string' ? dflt : key, second);
      },
      i18n: { language: 'en', changeLanguage: vi.fn() },
    }),
    Trans: ({ children }: { children?: unknown }) => children ?? null,
    initReactI18next: { type: '3rdParty', init: () => undefined },
    I18nextProvider: ({ children }: { children?: unknown }) => children ?? null,
  };
});

const apiGetMock = vi.fn();

vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/api')>();
  return {
    ...actual,
    apiGet: (url: string, ...rest: unknown[]) => apiGetMock(url, ...rest),
    apiPost: vi.fn(() => Promise.resolve({})),
    apiDelete: vi.fn(() => Promise.resolve({})),
  };
});

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    getApprovals: vi.fn(() => Promise.resolve([])),
    advanceApproval: vi.fn(() => Promise.resolve({})),
    startApprovalChain: vi.fn(() => Promise.resolve([])),
    simulateImpact: vi.fn(() => Promise.resolve({})),
    publishScenario: vi.fn(() => Promise.resolve({})),
    aiDraftChangeOrder: vi.fn(() => Promise.resolve({})),
  };
});

vi.mock('@/features/contracts/api', () => ({
  listContracts: vi.fn(() => Promise.resolve([])),
}));

vi.mock('@/features/claims-evidence', () => ({
  ProvabilityGauge: () => null,
  EvidenceThreadPanel: () => null,
}));

vi.mock('@/features/insights', () => ({
  InsightsPanel: () => null,
  InsightsToggleButton: () => null,
  useModuleInsights: () => ({ open: false, toggle: vi.fn(), insights: [], kpis: [], series: [] }),
}));

vi.mock('./ImpactSimulator', () => ({ ImpactSimulator: () => null }));
vi.mock('./AIDraftModal', () => ({ AIDraftModal: () => null }));

vi.mock('@/stores/useProjectContextStore', () => {
  const state = { activeProjectId: 'proj-1' };
  return {
    useProjectContextStore: (selector?: (s: typeof state) => unknown) =>
      selector ? selector(state) : state,
  };
});

vi.mock('@/stores/useToastStore', () => {
  const state = { addToast: vi.fn(), toasts: [], removeToast: vi.fn() };
  return {
    useToastStore: (selector?: (s: typeof state) => unknown) =>
      selector ? selector(state) : state,
  };
});

const auth = { userRole: 'admin', accessToken: '' };

vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (selector?: (s: typeof auth) => unknown) => (selector ? selector(auth) : auth),
}));

import { ChangeOrdersPage } from './ChangeOrdersPage';

/** A change order mirrored from variation order vo-9, later linked to ct-7. */
function order(metadata: Record<string, unknown>) {
  return {
    id: 'co-1',
    project_id: 'proj-1',
    code: 'CO-001',
    title: 'Revised ground floor slab',
    description: 'Thicker slab to carry the plant room.',
    reason_category: 'design_change',
    status: 'draft',
    submitted_by: null,
    submitted_by_name: null,
    approved_by: null,
    approved_by_name: null,
    rejected_by: null,
    rejected_by_name: null,
    submitted_at: null,
    approved_at: null,
    rejected_at: null,
    cost_impact: '12500.00',
    schedule_impact_days: 4,
    currency: 'EUR',
    metadata,
    item_count: 0,
    created_at: '2026-08-01T09:00:00Z',
    updated_at: '2026-08-01T10:00:00Z',
    current_approval_step: 0,
    items: [],
  };
}

function setTransport(record: ReturnType<typeof order>): void {
  apiGetMock.mockImplementation((url: string) => {
    if (url === '/v1/projects/') {
      return Promise.resolve([{ id: 'proj-1', name: 'Riverside', currency: 'EUR' }]);
    }
    if (url.startsWith('/v1/changeorders/co-1')) return Promise.resolve(record);
    return Promise.resolve([]);
  });
}

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/changeorders?highlight=co-1']}>
        <ChangeOrdersPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  navigateSpy.mockClear();
  apiGetMock.mockReset();
});

afterEach(() => cleanup());

describe('the related-record pills on a mirrored change order', () => {
  it('lands on the variation order the change order was created from', async () => {
    setTransport(
      order({
        origin: 'variations.convert_vr_to_vo',
        variation_order_id: 'vo-9',
        variation_request_id: 'vr-9',
      }),
    );
    renderDetail();

    fireEvent.click(await screen.findByText('From variation'));

    expect(navigateSpy).toHaveBeenCalledWith('/variations?tab=orders&highlight=vo-9');
    expect(navigateSpy).not.toHaveBeenCalledWith('/variations');
  });

  it('lands on the contract the change order applies to', async () => {
    setTransport(
      order({
        origin: 'variations.convert_vr_to_vo',
        variation_order_id: 'vo-9',
        variation_request_id: 'vr-9',
        contract_id: 'ct-7',
      }),
    );
    renderDetail();

    fireEvent.click(await screen.findByText('Applies to contract'));

    expect(navigateSpy).toHaveBeenCalledWith('/contracts?highlight=ct-7');
    expect(navigateSpy).not.toHaveBeenCalledWith('/contracts');
  });

  it('draws no variation pill for a change order that was not mirrored from one', async () => {
    // The control: the pill is drawn from the origin stamp, and a standalone
    // change order that happens to carry a variation id in its metadata is
    // not the case the pill is for.
    setTransport(order({ variation_order_id: 'vo-9' }));
    renderDetail();

    await screen.findByText('Revised ground floor slab');
    expect(screen.queryByText('From variation')).toBeNull();
  });
});

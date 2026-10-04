// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// An approved change order writes its scope into a bill as a section and its
// money into a revised-budget row, and the approval now stamps both ids on the
// order (metadata.writeback). The detail view turns them into pills that land
// on the bill row and on the budget lines. What is pinned: the destination,
// that the pills survive approved -> executed, that a draft, submitted or
// rejected order draws neither pill even when the stamp is present, and that
// an approved order without the stamp draws none rather than guessing.
//
// The harness is the one relatedPillsLandOnTheRecord.test.tsx uses.

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

function order(status: string, metadata: Record<string, unknown>) {
  return {
    id: 'co-1',
    project_id: 'proj-1',
    code: 'CO-001',
    title: 'Revised ground floor slab',
    description: 'Thicker slab to carry the plant room.',
    reason_category: 'design_change',
    status,
    submitted_by: null,
    submitted_by_name: null,
    approved_by: status === 'approved' || status === 'executed' ? 'u-2' : null,
    approved_by_name: null,
    rejected_by: null,
    rejected_by_name: null,
    submitted_at: null,
    approved_at: status === 'approved' || status === 'executed' ? '2026-08-02T09:00:00Z' : null,
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
    if (url.startsWith('/v1/projects/?')) {
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

const STAMP = {
  writeback: { boq_id: 'boq-3', boq_section_id: 'sec-9', budget_row_id: 'bud-4' },
};

beforeEach(() => {
  navigateSpy.mockClear();
  apiGetMock.mockReset();
});

afterEach(() => cleanup());

describe('an approved change order links to where it landed', () => {
  it('opens the bill on the section the approval added', async () => {
    setTransport(order('approved', STAMP));
    renderDetail();

    fireEvent.click(await screen.findByText('BOQ section'));

    expect(navigateSpy).toHaveBeenCalledWith('/boq/boq-3?highlight=sec-9');
  });

  it('opens the budget lines where the revised-budget row lives', async () => {
    setTransport(order('approved', STAMP));
    renderDetail();

    fireEvent.click(await screen.findByText('Revised budget'));

    expect(navigateSpy).toHaveBeenCalledWith('/finance?tab=budgets');
  });

  it('opens the bill without a row when the stamp names no section', async () => {
    setTransport(order('approved', { writeback: { boq_id: 'boq-3' } }));
    renderDetail();

    fireEvent.click(await screen.findByText('BOQ section'));

    expect(navigateSpy).toHaveBeenCalledWith('/boq/boq-3');
    expect(screen.queryByText('Revised budget')).toBeNull();
  });

  it('keeps both pills once the approved order is executed', async () => {
    // approved -> executed is the normal end of a change order, and the
    // execute step writes only the status, so the stamp is still there.
    setTransport(order('executed', STAMP));
    renderDetail();

    fireEvent.click(await screen.findByText('BOQ section'));
    expect(navigateSpy).toHaveBeenCalledWith('/boq/boq-3?highlight=sec-9');

    fireEvent.click(screen.getByText('Revised budget'));
    expect(navigateSpy).toHaveBeenCalledWith('/finance?tab=budgets');
  });

  it.each(['submitted', 'rejected'])('draws neither pill on a %s order', async (status) => {
    setTransport(order(status, STAMP));
    renderDetail();

    await screen.findByText('Revised ground floor slab');
    expect(screen.queryByText('BOQ section')).toBeNull();
    expect(screen.queryByText('Revised budget')).toBeNull();
  });

  it('draws neither pill on an order that is not approved', async () => {
    // A stamp on a draft cannot come from an approval; the pills describe
    // what an approval wrote, so the status is part of the condition.
    setTransport(order('draft', STAMP));
    renderDetail();

    await screen.findByText('Revised ground floor slab');
    expect(screen.queryByText('BOQ section')).toBeNull();
    expect(screen.queryByText('Revised budget')).toBeNull();
  });

  it('draws neither pill on an approved order that predates the stamp', async () => {
    setTransport(order('approved', {}));
    renderDetail();

    await screen.findByText('Revised ground floor slab');
    expect(screen.queryByText('BOQ section')).toBeNull();
    expect(screen.queryByText('Revised budget')).toBeNull();
  });
});

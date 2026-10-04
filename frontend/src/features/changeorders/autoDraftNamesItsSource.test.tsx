// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A change order the platform drafted from an answered RFI or a closed NCR
// (backend app/modules/changeorders/events.py) says so on its detail view, and
// both the banner and the "Related" pill land on the record it came from. The
// banner is only for drafts: once a person has submitted or decided it, the
// "nothing has been applied" line would no longer be true.
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
import { changeOrderSource } from './changeOrderSource';

/** A change order with the given metadata and status. */
function order(metadata: Record<string, unknown>, status = 'draft') {
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
    // The list, read through fetchProjectList, not the project detail.
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

beforeEach(() => {
  navigateSpy.mockClear();
  apiGetMock.mockReset();
});

afterEach(() => cleanup());

describe('changeOrderSource', () => {
  it('reads an RFI source and opens the RFI itself', () => {
    expect(
      changeOrderSource({ source: 'rfi', rfi_id: 'r 1', rfi_number: 'RFI-012', auto_drafted: true }),
    ).toEqual({
      kind: 'rfi',
      id: 'r 1',
      number: 'RFI-012',
      to: '/rfi/r%201',
      autoDrafted: true,
      amountUnread: null,
    });
  });

  it('reads an NCR source and opens the register on that NCR', () => {
    expect(changeOrderSource({ source: 'ncr', ncr_id: 'n-4', ncr_number: 'NCR-004' })).toEqual({
      kind: 'ncr',
      id: 'n-4',
      number: 'NCR-004',
      to: '/ncr?highlight=n-4',
      autoDrafted: false,
      amountUnread: null,
    });
  });

  it('hands over the written cost only when the amount could not be read', () => {
    const base = { source: 'ncr', ncr_id: 'n-4', ncr_cost_impact_raw: 'KWD 12.500' };
    expect(changeOrderSource({ ...base, amount_needs_review: 'ambiguous' })?.amountUnread).toBe('KWD 12.500');
    // A cost that was read keeps its raw text for the audit, but asks nothing.
    expect(changeOrderSource(base)?.amountUnread).toBeNull();
    expect(changeOrderSource({ ...base, amount_needs_review: '' })?.amountUnread).toBeNull();
  });

  it('names nothing without a source id or with an unknown source', () => {
    expect(changeOrderSource({ source: 'ncr' })).toBeNull();
    expect(changeOrderSource({ source: 'rfi', rfi_id: '' })).toBeNull();
    expect(changeOrderSource({ source: 'variations', variation_order_id: 'vo-9' })).toBeNull();
    expect(changeOrderSource(undefined)).toBeNull();
    // Only a literal true counts as drafted by the platform.
    expect(changeOrderSource({ source: 'ncr', ncr_id: 'n-4', auto_drafted: 'yes' })?.autoDrafted).toBe(false);
  });
});

describe('the change order detail view of an automatic draft', () => {
  it('says which NCR it was drafted from and opens that NCR', async () => {
    setTransport(
      order({ source: 'ncr', ncr_id: 'ncr-4', ncr_number: 'NCR-004', auto_drafted: true }),
    );
    renderDetail();

    expect(await screen.findByText('Drafted automatically from NCR-004')).toBeTruthy();
    fireEvent.click(screen.getByText('Open NCR-004'));

    expect(navigateSpy).toHaveBeenCalledWith('/ncr?highlight=ncr-4');
  });

  it('draws a Related pill to the NCR as well', async () => {
    setTransport(order({ source: 'ncr', ncr_id: 'ncr-4', ncr_number: 'NCR-004', auto_drafted: true }));
    renderDetail();

    const pill = await screen.findByTitle('Open the NCR this change order was raised from');
    fireEvent.click(pill);

    expect(navigateSpy).toHaveBeenCalledWith('/ncr?highlight=ncr-4');
  });

  it('opens the RFI itself, not the bare register, from the RFI pill', async () => {
    const record = {
      ...order({ source: 'rfi', rfi_id: 'rfi-7', rfi_number: 'RFI-007', auto_drafted: true }),
      linked_rfi_ids: ['rfi-7'],
    };
    apiGetMock.mockImplementation((url: string) => {
      if (url.startsWith('/v1/projects/?')) {
        return Promise.resolve([{ id: 'proj-1', name: 'Riverside', currency: 'EUR' }]);
      }
      if (url.startsWith('/v1/changeorders/co-1')) return Promise.resolve(record);
      return Promise.resolve([]);
    });
    renderDetail();

    expect(await screen.findByText('Drafted automatically from RFI-007')).toBeTruthy();
    // linked_rfi_ids already lists the RFI, so there is one RFI pill, not two.
    expect(screen.queryByTitle('Open the RFI this change order was raised from')).toBeNull();
    fireEvent.click(screen.getByTitle('rfi-7'));

    expect(navigateSpy).toHaveBeenCalledWith('/rfi/rfi-7');
    expect(navigateSpy).not.toHaveBeenCalledWith('/rfi');
  });

  it('drops the banner once the order is no longer a draft', async () => {
    setTransport(
      order({ source: 'ncr', ncr_id: 'ncr-4', ncr_number: 'NCR-004', auto_drafted: true }, 'submitted'),
    );
    renderDetail();

    await screen.findByText('Revised ground floor slab');
    expect(screen.queryByTestId('co-auto-draft-banner')).toBeNull();
    // The provenance pill stays: where it came from is still true.
    expect(screen.getByTitle('Open the NCR this change order was raised from')).toBeTruthy();
  });

  it('shows the cost as the NCR wrote it when it could not be read', async () => {
    setTransport(
      order({
        source: 'ncr',
        ncr_id: 'ncr-4',
        ncr_number: 'NCR-004',
        auto_drafted: true,
        amount_needs_review: 'ambiguous',
        ncr_cost_impact_raw: 'KWD 12.500',
      }),
    );
    renderDetail();

    const note = await screen.findByTestId('co-amount-unread');
    expect(note.textContent).toContain('"KWD 12.500"');
    expect(note.textContent).toContain('stays at 0 until you enter it');
  });

  it('asks for no amount when the NCR cost was read', async () => {
    setTransport(
      order({
        source: 'ncr',
        ncr_id: 'ncr-4',
        ncr_number: 'NCR-004',
        auto_drafted: true,
        ncr_cost_impact_raw: 'BRL 12.000,00',
      }),
    );
    renderDetail();

    await screen.findByText('Drafted automatically from NCR-004');
    expect(screen.queryByTestId('co-amount-unread')).toBeNull();
  });

  it('shows no banner on a change order a person raised by hand', async () => {
    setTransport(order({ source: 'ncr', ncr_id: 'ncr-4', ncr_number: 'NCR-004' }));
    renderDetail();

    await screen.findByText('Revised ground floor slab');
    expect(screen.queryByTestId('co-auto-draft-banner')).toBeNull();
  });
});
